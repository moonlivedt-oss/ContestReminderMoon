// crnative.exe - нативная часть ContestReminder (C++20, C++/WinRT, без
// сторонних библиотек).
//
// Две роли:
//   1. Уведомления Windows с кнопками (Центр уведомлений): `crnative toast
//   ...`.
//      Кнопки - протокол contestreminder://, поэтому они работают и когда
//      основная программа закрыта: Windows сам запустит crnative.exe с адресом
//      кнопки.
//   2. Сторож `crnative watch`: лёгкий фоновый процесс вместо целой программы в
//   трее.
//      Читает %APPDATA%\ContestReminder\contests.json, спит до ближайшего
//      порога напоминания и показывает уведомление. Пока основная программа
//      запущена (мьютекс Local\ContestReminder-App), сторож молчит - напоминает
//      она.
//
// Команды:
//   crnative register --app "<команда запуска программы>"   AUMID, протокол,
//   путь программы crnative unregister crnative toast --id ID --head TEXT
//   --body TEXT [--url URL] [--lang ru] [--urgent] crnative watch | stop |
//   status crnative "contestreminder://done?id=ID"                  действие
//   кнопки уведомления crnative selftest <отчёт.txt> проверка без побочных
//   эффектов
//
// Данные пишутся атомарно (временный файл + MoveFileEx) под мьютексом
// Local\ContestReminder-Data, общий формат - тот же JSON, что у Python-части.

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
// windows.h - строго первым (отдельный блок, чтобы форматтер не переставил)
#include <windows.h>

#include <shellapi.h>
#include <shlobj.h>
#include <winhttp.h>

#include <winrt/Windows.Data.Json.h>
#include <winrt/Windows.Data.Xml.Dom.h>
#include <winrt/Windows.Foundation.Collections.h>
#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.UI.Notifications.h>

#include <algorithm>
#include <cstdio>
#include <ctime>
#include <fstream>
#include <map>
#include <optional>
#include <sstream>
#include <string>
#include <vector>

using namespace winrt;
using namespace winrt::Windows::Data::Json;
using winrt::Windows::Data::Xml::Dom::XmlDocument;
using winrt::Windows::UI::Notifications::ToastNotification;
using winrt::Windows::UI::Notifications::ToastNotificationManager;

namespace {

constexpr wchar_t kAumid[] = L"MoonLight.ContestReminder";
constexpr wchar_t kProtocol[] = L"contestreminder";
constexpr wchar_t kAppKey[] = L"Software\\MoonLight\\ContestReminder";
constexpr wchar_t kAppMutex[] = L"Local\\ContestReminder-App";
constexpr wchar_t kWatchMutex[] = L"Local\\ContestReminder-Watcher";
constexpr wchar_t kStopEvent[] = L"Local\\ContestReminder-WatcherStop";
constexpr wchar_t kDataMutex[] = L"Local\\ContestReminder-Data";
constexpr int kSnoozed = -1;

// --- пути и файлы ----------------------------------------------------------

std::wstring known_folder(REFKNOWNFOLDERID id) {
  PWSTR p = nullptr;
  std::wstring out;
  if (SUCCEEDED(SHGetKnownFolderPath(id, 0, nullptr, &p)))
    out = p;
  CoTaskMemFree(p);
  return out;
}

std::wstring data_dir() {
  wchar_t buf[MAX_PATH];
  DWORD n = GetEnvironmentVariableW(L"APPDATA", buf,
                                    MAX_PATH); // как у Python: %APPDATA%
  std::wstring base = (n > 0 && n < MAX_PATH)
                          ? std::wstring(buf)
                          : known_folder(FOLDERID_RoamingAppData);
  return base + L"\\ContestReminder";
}

std::wstring self_path() {
  wchar_t buf[MAX_PATH];
  GetModuleFileNameW(nullptr, buf, MAX_PATH);
  return buf;
}

std::wstring self_dir() {
  std::wstring p = self_path();
  return p.substr(0, p.find_last_of(L"\\/"));
}

std::optional<std::wstring> read_utf8(const std::wstring &path) {
  std::ifstream f(path, std::ios::binary);
  if (!f)
    return std::nullopt;
  std::string s((std::istreambuf_iterator<char>(f)),
                std::istreambuf_iterator<char>());
  if (s.size() >= 3 && static_cast<unsigned char>(s[0]) == 0xEF)
    s.erase(0, 3); // BOM
  return std::wstring(to_hstring(s));
}

bool write_atomic(const std::wstring &path, const std::wstring &text) {
  std::wstring tmp = path + L".native.tmp";
  {
    std::ofstream f(tmp, std::ios::binary | std::ios::trunc);
    if (!f)
      return false;
    std::string u = to_string(text);
    f.write(u.data(), static_cast<std::streamsize>(u.size()));
    if (!f)
      return false;
  }
  return MoveFileExW(tmp.c_str(), path.c_str(),
                     MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) != 0;
}

struct DataLock { // общий с другими копиями crnative замок на contests.json
  HANDLE h;
  DataLock() : h(CreateMutexW(nullptr, FALSE, kDataMutex)) {
    if (h)
      WaitForSingleObject(h, 5000);
  }
  ~DataLock() {
    if (h) {
      ReleaseMutex(h);
      CloseHandle(h);
    }
  }
};

bool named_mutex_exists(const wchar_t *name) {
  HANDLE h = OpenMutexW(SYNCHRONIZE, FALSE, name);
  if (!h)
    return false;
  CloseHandle(h);
  return true;
}

// --- реестр -----------------------------------------------------------------

void reg_set(const std::wstring &key, const wchar_t *name,
             const std::wstring &value) {
  RegSetKeyValueW(HKEY_CURRENT_USER, key.c_str(), name, REG_SZ, value.c_str(),
                  static_cast<DWORD>((value.size() + 1) * sizeof(wchar_t)));
}

std::wstring reg_get(const std::wstring &key, const wchar_t *name) {
  wchar_t buf[2048];
  DWORD size = sizeof(buf);
  if (RegGetValueW(HKEY_CURRENT_USER, key.c_str(), name, RRF_RT_REG_SZ, nullptr,
                   buf, &size) != ERROR_SUCCESS)
    return L"";
  return buf;
}

void register_aumid() {
  std::wstring key =
      std::wstring(L"Software\\Classes\\AppUserModelId\\") + kAumid;
  reg_set(key, L"DisplayName", L"ContestReminder");
  std::wstring icon = self_dir() + L"\\icon.png";
  if (GetFileAttributesW(icon.c_str()) != INVALID_FILE_ATTRIBUTES)
    reg_set(key, L"IconUri", icon);
}

void register_all(const std::wstring &app_command) {
  register_aumid();
  std::wstring proto = std::wstring(L"Software\\Classes\\") + kProtocol;
  reg_set(proto, nullptr, L"URL:ContestReminder");
  reg_set(proto, L"URL Protocol", L"");
  reg_set(proto + L"\\DefaultIcon", nullptr, L"\"" + self_path() + L"\",0");
  reg_set(proto + L"\\shell\\open\\command", nullptr,
          L"\"" + self_path() + L"\" \"%1\"");
  if (!app_command.empty())
    reg_set(kAppKey, L"AppCommand", app_command);
  reg_set(kAppKey, L"Native", self_path());
}

void unregister_all() {
  RegDeleteTreeW(HKEY_CURRENT_USER,
                 (std::wstring(L"Software\\Classes\\") + kProtocol).c_str());
  RegDeleteTreeW(
      HKEY_CURRENT_USER,
      (std::wstring(L"Software\\Classes\\AppUserModelId\\") + kAumid).c_str());
  RegDeleteTreeW(HKEY_CURRENT_USER, kAppKey);
}

bool launch_app(const std::wstring &extra_args) {
  std::wstring cmd = reg_get(kAppKey, L"AppCommand");
  if (cmd.empty())
    return false;
  cmd += extra_args;
  STARTUPINFOW si{sizeof(si)};
  PROCESS_INFORMATION pi{};
  std::vector<wchar_t> buf(cmd.begin(), cmd.end());
  buf.push_back(0);
  if (!CreateProcessW(nullptr, buf.data(), nullptr, nullptr, FALSE,
                      DETACHED_PROCESS, nullptr, nullptr, &si, &pi))
    return false;
  CloseHandle(pi.hThread);
  CloseHandle(pi.hProcess);
  return true;
}

// --- настройки и языки
// ---------------------------------------------------------

struct Settings {
  std::wstring lang = L"ru";
  std::wstring token;
  int port = 47615;
};

std::wstring system_lang() {
  LANGID id = GetUserDefaultUILanguage();
  switch (PRIMARYLANGID(id)) {
  case LANG_RUSSIAN:
    return L"ru";
  case LANG_UKRAINIAN:
    return L"uk";
  case LANG_GERMAN:
    return L"de";
  default:
    return L"en";
  }
}

Settings load_settings() {
  Settings s;
  s.lang = system_lang();
  auto text = read_utf8(data_dir() + L"\\settings.json");
  JsonObject o{nullptr};
  if (text && JsonObject::TryParse(*text, o)) {
    std::wstring lang{o.GetNamedString(L"lang", L"auto")};
    if (lang == L"ru" || lang == L"en" || lang == L"uk" || lang == L"de")
      s.lang = lang;
    s.token = o.GetNamedString(L"bridge_token", L"");
    s.port = static_cast<int>(o.GetNamedNumber(L"bridge_port", 47615));
  }
  return s;
}

struct Strings {
  const wchar_t *reminder, *now, *passed, *snoozed, *open, *hour, *tomorrow,
      *done, *d, *h, *m, *at_moment;
};

const Strings &strings(const std::wstring &lang) {
  static const std::map<std::wstring, Strings> table = {
      {L"ru",
       {L"Напоминание ({})", L"Дедлайн сейчас!", L"Дедлайн прошёл",
        L"Отложенное напоминание", L"Открыть", L"Через 1 ч", L"Завтра",
        L"Готово", L"за {} дн", L"за {} ч", L"за {} мин", L"в момент"}},
      {L"uk",
       {L"Нагадування ({})", L"Дедлайн зараз!", L"Дедлайн минув",
        L"Відкладене нагадування", L"Відкрити", L"Через 1 год", L"Завтра",
        L"Готово", L"за {} дн", L"за {} год", L"за {} хв", L"в момент"}},
      {L"de",
       {L"Erinnerung ({})", L"Frist jetzt!", L"Frist abgelaufen",
        L"Verschobene Erinnerung", L"Öffnen", L"In 1 Std.", L"Morgen",
        L"Erledigt", L"{} T. vorher", L"{} Std. vorher", L"{} Min. vorher",
        L"zur Frist"}},
      {L"en",
       {L"Reminder ({})", L"Deadline now!", L"Deadline passed",
        L"Snoozed reminder", L"Open", L"In 1 h", L"Tomorrow", L"Done",
        L"{} d before", L"{} h before", L"{} min before", L"at the deadline"}},
  };
  auto it = table.find(lang);
  return it != table.end() ? it->second : table.at(L"en");
}

std::wstring fill(const wchar_t *pattern, const std::wstring &value) {
  std::wstring s = pattern;
  auto pos = s.find(L"{}");
  if (pos != std::wstring::npos)
    s.replace(pos, 2, value);
  return s;
}

std::wstring offset_text(const Strings &t, int minutes) {
  if (minutes <= 0)
    return t.at_moment;
  if (minutes % 1440 == 0)
    return fill(t.d, std::to_wstring(minutes / 1440));
  if (minutes % 60 == 0)
    return fill(t.h, std::to_wstring(minutes / 60));
  return fill(t.m, std::to_wstring(minutes));
}

// --- время
// ------------------------------------------------------------------------

// "2026-11-30T18:00:00" (местное время, как пишет Python) -> time_t; 0 - не
// разобрали
time_t parse_iso(const std::wstring &s) {
  std::tm tm{};
  int y = 0, mo = 0, d = 0, h = 0, mi = 0, sec = 0;
  int n =
      swscanf_s(s.c_str(), L"%d-%d-%dT%d:%d:%d", &y, &mo, &d, &h, &mi, &sec);
  if (n < 3)
    return 0;
  tm.tm_year = y - 1900;
  tm.tm_mon = mo - 1;
  tm.tm_mday = d;
  tm.tm_hour = h;
  tm.tm_min = mi;
  tm.tm_sec = sec;
  tm.tm_isdst = -1;
  return mktime(&tm);
}

std::wstring format_iso(time_t t) {
  std::tm tm{};
  localtime_s(&tm, &t);
  wchar_t buf[32];
  wcsftime(buf, 32, L"%Y-%m-%dT%H:%M:%S", &tm);
  return buf;
}

std::wstring format_human(time_t t) {
  std::tm tm{};
  localtime_s(&tm, &t);
  wchar_t buf[32];
  wcsftime(buf, 32, L"%d.%m.%Y  %H:%M", &tm);
  return buf;
}

time_t tomorrow_9am(time_t now) {
  std::tm tm{};
  localtime_s(&tm, &now);
  tm.tm_mday += 1;
  tm.tm_hour = 9;
  tm.tm_min = 0;
  tm.tm_sec = 0;
  tm.tm_isdst = -1;
  return mktime(&tm);
}

// --- конкурсы и логика напоминаний (как reminders.due_reminders в Python)
// ----------------

struct Due {
  int fire = 0;          // смещение для показа или kSnoozed
  std::vector<int> mark; // пороги, которые отметить
  bool expired = false;
};

std::vector<int> int_list(const JsonObject &o, const wchar_t *key) {
  std::vector<int> out;
  if (!o.HasKey(key) ||
      o.GetNamedValue(key).ValueType() != JsonValueType::Array)
    return out;
  for (auto v : o.GetNamedArray(key))
    if (v.ValueType() == JsonValueType::Number)
      out.push_back(static_cast<int>(v.GetNumber()));
  return out;
}

std::wstring str_or_empty(const JsonObject &o, const wchar_t *key) {
  if (!o.HasKey(key) ||
      o.GetNamedValue(key).ValueType() != JsonValueType::String)
    return L"";
  return std::wstring(o.GetNamedString(key));
}

std::optional<Due> due_for(const JsonObject &c, time_t now) {
  if (c.HasKey(L"done") &&
      c.GetNamedValue(L"done").ValueType() == JsonValueType::Boolean &&
      c.GetNamedBoolean(L"done"))
    return std::nullopt;
  time_t deadline = parse_iso(str_or_empty(c, L"deadline"));
  time_t snooze = parse_iso(str_or_empty(c, L"snoozed_until"));
  if (snooze && now >= snooze)
    return Due{kSnoozed, {}, deadline && deadline < now};
  if (!deadline)
    return std::nullopt;
  auto notified = int_list(c, L"notified");
  Due d;
  for (int off : int_list(c, L"reminders")) {
    if (std::find(notified.begin(), notified.end(), off) != notified.end())
      continue;
    if (now >= deadline - static_cast<time_t>(off) * 60)
      d.mark.push_back(off);
  }
  if (d.mark.empty())
    return std::nullopt;
  d.fire = *std::min_element(d.mark.begin(), d.mark.end()); // самое срочное
  d.expired = deadline < now;
  return d;
}

// ближайший будущий момент, когда кому-то пора напомнить (0 - никогда)
time_t next_wake(const JsonArray &list, time_t now) {
  time_t best = 0;
  auto consider = [&](time_t t) {
    if (t > now && (!best || t < best))
      best = t;
  };
  for (auto v : list) {
    if (v.ValueType() != JsonValueType::Object)
      continue;
    auto c = v.GetObject();
    if (c.HasKey(L"done") &&
        c.GetNamedValue(L"done").ValueType() == JsonValueType::Boolean &&
        c.GetNamedBoolean(L"done"))
      continue;
    consider(parse_iso(str_or_empty(c, L"snoozed_until")));
    time_t deadline = parse_iso(str_or_empty(c, L"deadline"));
    if (!deadline)
      continue;
    auto notified = int_list(c, L"notified");
    for (int off : int_list(c, L"reminders"))
      if (std::find(notified.begin(), notified.end(), off) == notified.end())
        consider(deadline - static_cast<time_t>(off) * 60);
  }
  return best;
}

// --- уведомления
// ----------------------------------------------------------------------

std::wstring xml_escape(const std::wstring &s) {
  std::wstring out;
  for (wchar_t ch : s) {
    switch (ch) {
    case L'&':
      out += L"&amp;";
      break;
    case L'<':
      out += L"&lt;";
      break;
    case L'>':
      out += L"&gt;";
      break;
    case L'"':
      out += L"&quot;";
      break;
    case L'\'':
      out += L"&apos;";
      break;
    default:
      out += ch;
    }
  }
  return out;
}

std::wstring toast_xml(const std::wstring &id, const std::wstring &head,
                       const std::wstring &body, const std::wstring &url,
                       const Strings &t, bool urgent) {
  std::wstring base = std::wstring(kProtocol) + L"://";
  std::wostringstream x;
  x << L"<toast launch=\"" << xml_escape(base + L"open?id=" + id)
    << L"\" activationType=\"protocol\"";
  if (urgent)
    x << L" scenario=\"reminder\"";
  x << L"><visual><binding template=\"ToastGeneric\"><text>" << xml_escape(head)
    << L"</text><text>" << xml_escape(body)
    << L"</text></binding></visual><actions>";
  if (!url.empty() &&
      (url.rfind(L"http://", 0) == 0 || url.rfind(L"https://", 0) == 0))
    x << L"<action content=\"" << xml_escape(t.open)
      << L"\" activationType=\"protocol\" arguments=\"" << xml_escape(url)
      << L"\"/>";
  x << L"<action content=\"" << xml_escape(t.hour)
    << L"\" activationType=\"protocol\" arguments=\""
    << xml_escape(base + L"snooze?id=" + id + L"&min=60") << L"\"/>";
  x << L"<action content=\"" << xml_escape(t.tomorrow)
    << L"\" activationType=\"protocol\" arguments=\""
    << xml_escape(base + L"snooze?id=" + id + L"&min=tomorrow") << L"\"/>";
  x << L"<action content=\"" << xml_escape(t.done)
    << L"\" activationType=\"protocol\" arguments=\""
    << xml_escape(base + L"done?id=" + id) << L"\"/>";
  x << L"</actions><audio "
       L"src=\"ms-winsoundevent:Notification.Reminder\"/></toast>";
  return x.str();
}

bool show_toast(const std::wstring &id, const std::wstring &head,
                const std::wstring &body, const std::wstring &url,
                const std::wstring &lang, bool urgent) {
  try {
    register_aumid();
    XmlDocument doc;
    doc.LoadXml(toast_xml(id, head, body, url, strings(lang), urgent));
    ToastNotification toast(doc);
    toast.Tag(hstring(id.substr(0, 64)));
    toast.Group(L"cr");
    ToastNotificationManager::CreateToastNotifier(kAumid).Show(toast);
    return true;
  } catch (...) {
    return false;
  }
}

void remove_toast(const std::wstring &id) {
  try {
    ToastNotificationManager::History().Remove(hstring(id.substr(0, 64)), L"cr",
                                               kAumid);
  } catch (...) {
  }
}

std::wstring head_for(const Due &d, const Strings &t) {
  if (d.fire == kSnoozed)
    return t.snoozed;
  if (d.expired)
    return t.passed;
  if (d.fire == 0)
    return t.now;
  return fill(t.reminder, offset_text(t, d.fire));
}

// --- действия кнопок
// ------------------------------------------------------------------------

std::map<std::wstring, std::wstring> parse_query(const std::wstring &uri) {
  std::map<std::wstring, std::wstring> q;
  auto qpos = uri.find(L'?');
  auto path_start = uri.find(L"://");
  std::wstring action =
      uri.substr(path_start == std::wstring::npos ? 0 : path_start + 3,
                 (qpos == std::wstring::npos ? uri.size() : qpos) -
                     (path_start == std::wstring::npos ? 0 : path_start + 3));
  while (!action.empty() && action.back() == L'/')
    action.pop_back();
  q[L"action"] = action;
  if (qpos == std::wstring::npos)
    return q;
  std::wstringstream ss(uri.substr(qpos + 1));
  std::wstring pair;
  while (std::getline(ss, pair, L'&')) {
    auto eq = pair.find(L'=');
    if (eq != std::wstring::npos)
      q[pair.substr(0, eq)] = pair.substr(eq + 1);
  }
  return q;
}

bool safe_id(const std::wstring &id) {
  return !id.empty() && id.size() <= 64 &&
         std::all_of(id.begin(), id.end(), [](wchar_t c) {
           return iswalnum(c) || c == L'-' || c == L'_';
         });
}

// POST в мост запущенной программы; true - программа приняла
bool post_to_app(const Settings &s, const std::wstring &json) {
  if (s.token.empty())
    return false;
  bool ok = false;
  HINTERNET ses = WinHttpOpen(L"crnative", WINHTTP_ACCESS_TYPE_NO_PROXY,
                              nullptr, nullptr, 0);
  if (!ses)
    return false;
  WinHttpSetTimeouts(ses, 1000, 1000, 2000, 2000);
  HINTERNET con =
      WinHttpConnect(ses, L"127.0.0.1", static_cast<INTERNET_PORT>(s.port), 0);
  HINTERNET req = con ? WinHttpOpenRequest(con, L"POST", L"/action", nullptr,
                                           nullptr, nullptr, 0)
                      : nullptr;
  if (req) {
    std::string body = to_string(json);
    const wchar_t *headers = L"Content-Type: application/json\r\n";
    if (WinHttpSendRequest(req, headers, static_cast<DWORD>(-1L), body.data(),
                           static_cast<DWORD>(body.size()),
                           static_cast<DWORD>(body.size()), 0) &&
        WinHttpReceiveResponse(req, nullptr)) {
      DWORD code = 0, len = sizeof(code);
      WinHttpQueryHeaders(req,
                          WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                          nullptr, &code, &len, nullptr);
      ok = code == 200;
    }
    WinHttpCloseHandle(req);
  }
  if (con)
    WinHttpCloseHandle(con);
  WinHttpCloseHandle(ses);
  return ok;
}

// программа закрыта - правим contests.json сами
bool apply_offline(const std::wstring &action, const std::wstring &id,
                   const std::wstring &minutes) {
  DataLock lock;
  std::wstring path = data_dir() + L"\\contests.json";
  auto text = read_utf8(path);
  JsonArray list{nullptr};
  if (!text || !JsonArray::TryParse(*text, list))
    return false;
  time_t now = time(nullptr);
  bool changed = false;
  for (auto v : list) {
    if (v.ValueType() != JsonValueType::Object)
      continue;
    auto c = v.GetObject();
    if (str_or_empty(c, L"id") != id)
      continue;
    if (action == L"done") {
      c.SetNamedValue(L"done", JsonValue::CreateBooleanValue(true));
      c.SetNamedValue(L"snoozed_until", JsonValue::CreateNullValue());
    } else if (action == L"snooze") {
      time_t when = minutes == L"tomorrow" ? tomorrow_9am(now)
                                           : now + _wtoi(minutes.c_str()) * 60;
      if (when <= now)
        when = now + 3600;
      c.SetNamedValue(L"snoozed_until",
                      JsonValue::CreateStringValue(format_iso(when)));
    }
    changed = true;
  }
  return changed && write_atomic(path, std::wstring(list.Stringify()));
}

int handle_uri(const std::wstring &uri) {
  auto q = parse_query(uri);
  const std::wstring &action = q[L"action"];
  std::wstring id = q[L"id"];
  if (action != L"open" && action != L"done" && action != L"snooze")
    return 2;
  if (!id.empty() && !safe_id(id))
    return 2;
  Settings s = load_settings();

  JsonObject msg;
  msg.SetNamedValue(L"token", JsonValue::CreateStringValue(s.token));
  msg.SetNamedValue(L"action", JsonValue::CreateStringValue(action));
  msg.SetNamedValue(L"id", JsonValue::CreateStringValue(id));
  msg.SetNamedValue(L"min", JsonValue::CreateStringValue(q[L"min"]));
  if (post_to_app(s, std::wstring(msg.Stringify())))
    return 0;

  if (action == L"open")
    return launch_app(L"") ? 0 : 1;
  if (id.empty())
    return 2;
  bool ok = apply_offline(action, id, q[L"min"]);
  remove_toast(id);
  return ok ? 0 : 1;
}

// --- сторож
// -------------------------------------------------------------------------------------

// один проход: показать всё, что пора; вернуть момент следующего пробуждения
time_t watch_tick(time_t now) {
  DataLock lock;
  std::wstring path = data_dir() + L"\\contests.json";
  auto text = read_utf8(path);
  JsonArray list{nullptr};
  if (!text || !JsonArray::TryParse(*text, list))
    return 0;
  Settings s = load_settings();
  const Strings &t = strings(s.lang);
  bool changed = false;
  for (auto v : list) {
    if (v.ValueType() != JsonValueType::Object)
      continue;
    auto c = v.GetObject();
    auto due = due_for(c, now);
    if (!due)
      continue;
    if (due->fire == kSnoozed) {
      c.SetNamedValue(L"snoozed_until", JsonValue::CreateNullValue());
    } else {
      auto notified =
          c.HasKey(L"notified") && c.GetNamedValue(L"notified").ValueType() ==
                                       JsonValueType::Array
              ? c.GetNamedArray(L"notified")
              : JsonArray();
      for (int off : due->mark)
        notified.Append(JsonValue::CreateNumberValue(off));
      c.SetNamedValue(L"notified", notified);
    }
    changed = true;
    std::wstring body = str_or_empty(c, L"title");
    time_t deadline = parse_iso(str_or_empty(c, L"deadline"));
    if (deadline)
      body += L"\n" + format_human(deadline);
    show_toast(str_or_empty(c, L"id"), head_for(*due, t), body,
               str_or_empty(c, L"url"), s.lang,
               due->fire == 0 || due->fire == kSnoozed);
  }
  if (changed)
    write_atomic(path, std::wstring(list.Stringify()));
  return next_wake(list, now);
}

int watch() {
  HANDLE single = CreateMutexW(nullptr, TRUE, kWatchMutex);
  if (GetLastError() == ERROR_ALREADY_EXISTS)
    return 0; // уже сторожит другая копия
  HANDLE stop = CreateEventW(nullptr, TRUE, FALSE, kStopEvent);
  ResetEvent(stop);
  std::wstring dir = data_dir();
  CreateDirectoryW(dir.c_str(), nullptr);
  HANDLE change = FindFirstChangeNotificationW(
      dir.c_str(), FALSE,
      FILE_NOTIFY_CHANGE_LAST_WRITE | FILE_NOTIFY_CHANGE_FILE_NAME);
  for (;;) {
    time_t now = time(nullptr);
    DWORD wait_ms =
        5 * 60 * 1000; // не реже раза в 5 минут: смена времени, сон компьютера
    if (!named_mutex_exists(kAppMutex)) { // программа закрыта - напоминаем сами
      time_t next = watch_tick(now);
      if (next)
        wait_ms = static_cast<DWORD>(
            std::clamp<long long>((next - now) * 1000LL + 500, 1000, wait_ms));
    } else {
      wait_ms = 60 * 1000;
    }
    // перед сном отдаём системе страницы, которые подняли WinRT и XML
    // уведомлений: сторож почти всё время спит, держать их в памяти незачем
    SetProcessWorkingSetSize(GetCurrentProcess(), static_cast<SIZE_T>(-1),
                             static_cast<SIZE_T>(-1));
    HANDLE handles[2] = {stop, change};
    DWORD n = change != INVALID_HANDLE_VALUE ? 2 : 1;
    DWORD r = WaitForMultipleObjects(n, handles, FALSE, wait_ms);
    if (r == WAIT_OBJECT_0)
      break;
    if (r == WAIT_OBJECT_0 + 1) {
      FindNextChangeNotification(change);
      Sleep(300); // дать Python дописать файл целиком
    }
  }
  if (change != INVALID_HANDLE_VALUE)
    FindCloseChangeNotification(change);
  CloseHandle(stop);
  ReleaseMutex(single);
  CloseHandle(single);
  return 0;
}

int stop_watcher() {
  HANDLE ev = OpenEventW(EVENT_MODIFY_STATE, FALSE, kStopEvent);
  if (!ev)
    return 0;
  SetEvent(ev);
  CloseHandle(ev);
  for (int i = 0; i < 30 && named_mutex_exists(kWatchMutex); ++i)
    Sleep(100);
  return 0;
}

// --- самопроверка
// ---------------------------------------------------------------------------------

int selftest(const std::wstring &report_path) {
  std::wostringstream out;
  int failed = 0;
  auto check = [&](const wchar_t *name, bool ok) {
    out << (ok ? L"ok    " : L"FAIL  ") << name << L"\n";
    if (!ok)
      ++failed;
  };
  time_t now = parse_iso(L"2026-10-11T12:00:00");
  check(L"разбор даты", now != 0 && format_iso(now) == L"2026-10-11T12:00:00");

  JsonArray list{nullptr};
  bool parsed = JsonArray::TryParse(
      LR"([{"id":"a1","title":"Арт","deadline":"2026-10-11T12:30:00","reminders":[1440,60,0],"notified":[1440],"done":false},
             {"id":"b2","title":"B","deadline":"2026-10-20T12:00:00","reminders":[60],"notified":[],"done":true},
             {"id":"c3","title":"C","deadline":null,"reminders":[],"notified":[],"snoozed_until":"2026-10-11T11:59:00"}])",
      list);
  check(L"JSON (Windows.Data.Json)", parsed && list.Size() == 3);
  if (parsed) {
    auto a = due_for(list.GetObjectAt(0), now);
    check(L"порог: самое срочное из пропущенных",
          a && a->fire == 60 && a->mark.size() == 1);
    check(L"выполненные молчат", !due_for(list.GetObjectAt(1), now));
    auto c = due_for(list.GetObjectAt(2), now);
    check(L"отложенное важнее порогов", c && c->fire == kSnoozed);
    check(L"следующее пробуждение",
          next_wake(list, now) == parse_iso(L"2026-10-11T12:30:00"));
  }
  auto q = parse_query(L"contestreminder://snooze/?id=a1&min=60");
  check(L"адрес кнопки",
        q[L"action"] == L"snooze" && q[L"id"] == L"a1" && q[L"min"] == L"60");
  check(L"id без мусора",
        safe_id(L"a1b2") && !safe_id(L"..\\x") && !safe_id(L""));
  try {
    XmlDocument doc;
    doc.LoadXml(toast_xml(L"a1", L"Заголовок <&>", L"Текст \"кавычки\"",
                          L"https://x.io/?a=1&b=2", strings(L"de"), true));
    check(L"XML уведомления", doc.SelectNodes(L"//action").Size() == 4);
  } catch (...) {
    check(L"XML уведомления", false);
  }
  check(L"смещения", offset_text(strings(L"ru"), 1440) == L"за 1 дн" &&
                         offset_text(strings(L"en"), 0) == L"at the deadline");
  out << (failed ? L"\nFAIL" : L"\nOK") << L" (crnative)\n";
  std::wstring report = out.str();
  if (!report_path.empty()) {
    std::ofstream f(report_path, std::ios::binary);
    std::string u = to_string(report);
    f.write(u.data(), static_cast<std::streamsize>(u.size()));
  }
  return failed ? 1 : 0;
}

std::wstring arg_value(const std::vector<std::wstring> &args,
                       const wchar_t *name) {
  for (size_t i = 0; i + 1 < args.size(); ++i)
    if (args[i] == name)
      return args[i + 1];
  return L"";
}

bool has_flag(const std::vector<std::wstring> &args, const wchar_t *name) {
  return std::find(args.begin(), args.end(), name) != args.end();
}

} // namespace

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) {
  init_apartment(apartment_type::multi_threaded);
  int argc = 0;
  LPWSTR *argv = CommandLineToArgvW(GetCommandLineW(), &argc);
  std::vector<std::wstring> args(argv + 1, argv + argc);
  LocalFree(argv);
  if (args.empty())
    return 2;
  const std::wstring &cmd = args[0];

  if (cmd.rfind(std::wstring(kProtocol) + L":", 0) == 0)
    return handle_uri(cmd);
  if (cmd == L"register") {
    register_all(arg_value(args, L"--app"));
    return 0;
  }
  if (cmd == L"unregister") {
    stop_watcher();
    unregister_all();
    return 0;
  }
  if (cmd == L"toast")
    return show_toast(arg_value(args, L"--id"), arg_value(args, L"--head"),
                      arg_value(args, L"--body"), arg_value(args, L"--url"),
                      arg_value(args, L"--lang").empty()
                          ? L"ru"
                          : arg_value(args, L"--lang"),
                      has_flag(args, L"--urgent"))
               ? 0
               : 1;
  if (cmd == L"remove") {
    remove_toast(arg_value(args, L"--id"));
    return 0;
  }
  if (cmd == L"watch")
    return watch();
  if (cmd == L"stop")
    return stop_watcher();
  if (cmd == L"status")
    return named_mutex_exists(kWatchMutex) ? 0 : 1;
  if (cmd == L"selftest")
    return selftest(args.size() > 1 ? args[1] : L"");
  return 2;
}
