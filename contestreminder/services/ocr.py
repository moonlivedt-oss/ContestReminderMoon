"""OCR области экрана через встроенный Windows.Media.Ocr (winsdk) + захват mss.

Тот же движок, что в AutoTranslator: языковые пакеты (ru, en-US) должны стоять в
системе (обычно уже есть на Win11). WinRT-корутины гоняем синхронно через asyncio.
"""
from __future__ import annotations

import asyncio
import io

from PIL import Image


def grab_region(left: int, top: int, width: int, height: int) -> Image.Image:
    import mss

    with mss.mss() as sct:
        shot = sct.grab({"left": left, "top": top, "width": width, "height": height})
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


async def _recognize(png_bytes: bytes, lang_tag: str | None) -> str:
    from winsdk.windows.globalization import Language
    from winsdk.windows.graphics.imaging import BitmapDecoder
    from winsdk.windows.media.ocr import OcrEngine
    from winsdk.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream.get_output_stream_at(0))
    writer.write_bytes(png_bytes)
    await writer.store_async()
    await writer.flush_async()
    stream.seek(0)

    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()

    engine = None
    if lang_tag:
        engine = OcrEngine.try_create_from_language(Language(lang_tag))
    if engine is None:
        engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise RuntimeError(
            "Не удалось создать OCR-движок. Установите языковой пакет в "
            "Параметрах Windows (Время и язык -> Язык).")

    result = await engine.recognize_async(bitmap)
    lines = [line.text for line in result.lines]
    return "\n".join(lines) if lines else (result.text or "")


def ocr_image(image: Image.Image, lang_tag: str | None = None) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return asyncio.run(_recognize(buf.getvalue(), lang_tag)).strip()


def ocr_region(left: int, top: int, width: int, height: int,
               lang_tag: str | None = None) -> str:
    return ocr_image(grab_region(left, top, width, height), lang_tag)
