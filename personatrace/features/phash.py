"""Perceptual hash (aHash) for exact same-image reuse detection only.

Stdlib first, with optional Pillow for JPEG/WebP and other formats
when Pillow is installed. Supported stdlib inputs: BMP (24/32-bit
uncompressed), PNG (non-interlaced, 8/16-bit, colour types 0, 2, 3, 4, 6)
and PPM (P5/P6). When Pillow is present it is used for formats the
stdlib decoder does not handle (JPEG, WebP, GIF, TIFF, …); when it is
absent those formats are not claimed as images. The image is reduced
to 8x8 greyscale by block averaging and each pixel is compared with
the mean: 1 bit per pixel, 64 bits total.

Non-image bytes: ``ahash`` falls back to a hashlib-based pseudo-hash
documented here as DEMO-GRADE ONLY. A pseudo-hash match must never be
presented as an image-reuse match. Callers must check
``is_image_bytes`` first, or use ``is_reuse_bytes``, which returns
False for non-image input. This module performs NO face identification
of any kind: it compares whole-image hashes, never faces or identities.
"""

import hashlib
import struct
import zlib

__all__ = ["ahash", "hamming", "is_reuse", "is_image_bytes", "is_reuse_bytes"]


def is_image_bytes(data: bytes) -> bool:
    """True if *data* parses as a supported image format."""
    if not isinstance(data, (bytes, bytearray)):
        return False
    try:
        _decode_image(bytes(data))
        return True
    except Exception:
        return False


def _decode_image(data: bytes):
    """Return (width, height, greyscale bytes) or raise ValueError."""
    # Pillow path for JPEG/WebP/etc. — only for formats the stdlib
    # decoder below does not already handle, so stdlib behaviour for
    # BMP/PNG/PPM is unchanged.
    if data[:2] not in (b"BM", b"P5", b"P6") and data[:8] != b"\x89PNG\r\n\x1a\n":
        try:
            from PIL import Image
            import io as _io

            with Image.open(_io.BytesIO(data)) as im:
                grey_im = im.convert("L")
                width, height = grey_im.size
                return width, height, grey_im.tobytes()
        except Exception:
            pass
    if data[:2] == b"BM":
        return _decode_bmp(data)
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return _decode_png(data)
    if data[:2] in (b"P5", b"P6"):
        return _decode_ppm(data)
    raise ValueError("unsupported image format")


def _decode_bmp(data: bytes):
    if len(data) < 54:
        raise ValueError("truncated BMP")
    offset = struct.unpack_from("<I", data, 10)[0]
    header_size = struct.unpack_from("<I", data, 14)[0]
    if header_size < 40:
        raise ValueError("unsupported BMP header")
    width = struct.unpack_from("<i", data, 18)[0]
    height = struct.unpack_from("<i", data, 22)[0]
    planes, bpp = struct.unpack_from("<HH", data, 26)
    compression = struct.unpack_from("<I", data, 30)[0]
    if bpp not in (24, 32) or compression != 0 or width <= 0 or height == 0:
        raise ValueError("unsupported BMP variant")
    top_down = height < 0
    height = abs(height)
    bytes_per_px = bpp // 8
    row_size = ((width * bpp + 31) // 32) * 4
    grey = bytearray(width * height)
    for y in range(height):
        src_y = y if top_down else height - 1 - y
        row_start = offset + src_y * row_size
        for x in range(width):
            px = row_start + x * bytes_per_px
            if px + 2 >= len(data):
                raise ValueError("truncated BMP pixels")
            b, g, r = data[px], data[px + 1], data[px + 2]
            grey[y * width + x] = (r * 299 + g * 587 + b * 114) // 1000
    return width, height, bytes(grey)


def _decode_ppm(data: bytes):
    # Tokenise header: magic, width, height, maxval, then binary pixels.
    parts, idx, count = [], 0, 0
    kind = data[:2]
    while count < 3 and idx < len(data):
        # Skip whitespace and comments.
        while idx < len(data) and chr(data[idx]) in " \t\r\n":
            idx += 1
        if idx < len(data) and data[idx : idx + 1] == b"#":
            while idx < len(data) and data[idx] != 0x0A:
                idx += 1
            continue
        start = idx
        while idx < len(data) and chr(data[idx]) not in " \t\r\n":
            idx += 1
        parts.append(data[start:idx])
        count += 1
    if len(parts) != 3:
        raise ValueError("bad PPM header")
    width, height, maxval = int(parts[0]), int(parts[1]), int(parts[2])
    idx += 1  # single whitespace byte after maxval
    if width <= 0 or height <= 0 or maxval <= 0 or maxval > 65535:
        raise ValueError("bad PPM dimensions")
    px = data[idx:]
    grey = bytearray(width * height)
    if kind == b"P6":
        need = width * height * 3 * (2 if maxval > 255 else 1)
        if len(px) < need:
            raise ValueError("truncated PPM")
        step = 2 if maxval > 255 else 1
        for i in range(width * height):
            o = i * 3 * step
            if step == 2:
                r = px[o]
                g = px[o + 2]
                b = px[o + 4]
            else:
                r, g, b = px[o], px[o + 1], px[o + 2]
            grey[i] = (r * 299 + g * 587 + b * 114) // 1000
    else:  # P5 greyscale
        need = width * height * (2 if maxval > 255 else 1)
        if len(px) < need:
            raise ValueError("truncated PPM")
        step = 2 if maxval > 255 else 1
        for i in range(width * height):
            grey[i] = px[i * step]
    return width, height, bytes(grey)


def _decode_png(data: bytes):
    pos, idat, plte, trns = 8, bytearray(), None, None
    width = height = bit_depth = color_type = interlace = None
    while pos + 8 <= len(data):
        length = struct.unpack_from(">I", data, pos)[0]
        ctype = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        if ctype == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(
                ">IIBBBBB", chunk
            )
        elif ctype == b"PLTE":
            plte = chunk
        elif ctype == b"tRNS":
            trns = chunk
        elif ctype == b"IDAT":
            idat.extend(chunk)
        elif ctype == b"IEND":
            break
        pos += 12 + length
    if width is None or interlace != 0 or bit_depth not in (8, 16):
        raise ValueError("unsupported PNG variant")
    raw = zlib.decompress(bytes(idat))
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    step = 2 if bit_depth == 16 else 1
    bpp = channels * step  # bytes per pixel for filtering
    stride = width * channels * step
    pixels, prev, offset = [], bytearray(stride), 0
    for _ in range(height):
        ftype = raw[offset]
        offset += 1
        line = bytearray(raw[offset : offset + stride])
        offset += stride
        if ftype == 1:  # Sub
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:  # Average
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + (a + prev[i]) // 2) & 0xFF
        elif ftype == 4:  # Paeth
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        elif ftype != 0:
            raise ValueError("unknown PNG filter")
        prev = line
        pixels.append(bytes(line))
    grey = bytearray(width * height)
    for y in range(height):
        line = pixels[y]
        for x in range(width):
            o = x * channels * step
            if color_type == 0:
                v = line[o]
            elif color_type == 2:
                r, g, b = line[o], line[o + step], line[o + 2 * step]
                v = (r * 299 + g * 587 + b * 114) // 1000
            elif color_type == 3:
                if plte is None or line[o] * 3 + 2 >= len(plte):
                    raise ValueError("bad PNG palette index")
                r, g, b = plte[line[o] * 3 : line[o] * 3 + 3]
                v = (r * 299 + g * 587 + b * 114) // 1000
            elif color_type == 4:
                v = line[o]
            else:  # 6 RGBA
                r, g, b = line[o], line[o + step], line[o + 2 * step]
                v = (r * 299 + g * 587 + b * 114) // 1000
            grey[y * width + x] = v
    return width, height, bytes(grey)


def _average_hash(width: int, height: int, grey: bytes) -> int:
    # Block-average down to 8x8, then threshold at the mean.
    small = []
    for gy in range(8):
        y0, y1 = gy * height // 8, (gy + 1) * height // 8 or 1
        for gx in range(8):
            x0, x1 = gx * width // 8, (gx + 1) * width // 8 or 1
            total = count = 0
            for y in range(y0, max(y1, y0 + 1)):
                for x in range(x0, max(x1, x0 + 1)):
                    total += grey[y * width + x]
                    count += 1
            small.append(total // max(count, 1))
    mean = sum(small) // 64
    value = 0
    for i, v in enumerate(small):
        if v >= mean:
            value |= 1 << (63 - i)
    return value


def ahash(image_bytes: bytes) -> int:
    """Return the 64-bit average hash of an image.

    For bytes that do not parse as a supported image, returns a
    hashlib-based pseudo-hash (demo-grade only; see module docstring).
    Never present a pseudo-hash match as an image-reuse match.
    """
    try:
        width, height, grey = _decode_image(bytes(image_bytes))
    except Exception:
        digest = hashlib.sha256(bytes(image_bytes)).digest()
        return int.from_bytes(digest[:8], "big")
    return _average_hash(width, height, grey)


def hamming(a: int, b: int) -> int:
    """Hamming distance between two 64-bit hashes (0-64)."""
    return bin(int(a) ^ int(b)).count("1")


def is_reuse(a: int, b: int, threshold: int = 10) -> bool:
    """True when two hashes are within *threshold* bits (default 10).

    Callers must only pass hashes of verified images (see
    :func:`is_image_bytes`); use :func:`is_reuse_bytes` for raw bytes.
    """
    return hamming(a, b) <= threshold


def is_reuse_bytes(a: bytes, b: bytes, threshold: int = 10) -> bool:
    """Same-image reuse check over raw bytes; False for non-images."""
    if not (is_image_bytes(a) and is_image_bytes(b)):
        return False
    return is_reuse(ahash(a), ahash(b), threshold=threshold)
