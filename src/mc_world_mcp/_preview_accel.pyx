# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: initializedcheck=False

from libc.math cimport cos, sin
from libc.stdint cimport int64_t, uint64_t


cdef int _bits_for_palette(Py_ssize_t size):
    cdef int bits = 0
    cdef Py_ssize_t value = size - 1
    while value > 0:
        bits += 1
        value >>= 1
    if bits < 4:
        return 4
    return bits


cpdef list decode_indices(object data, Py_ssize_t palette_size):
    cdef list values = [0] * 4096
    if data is None:
        return values

    cdef int bits = _bits_for_palette(palette_size)
    cdef int values_per_long = 64 // bits
    cdef uint64_t mask = (<uint64_t>1 << bits) - 1
    cdef Py_ssize_t long_count = len(data)
    cdef Py_ssize_t i
    cdef Py_ssize_t long_index
    cdef int start
    cdef int64_t signed_value
    cdef uint64_t raw

    for i in range(4096):
        long_index = i // values_per_long
        if long_index < long_count:
            start = (i % values_per_long) * bits
            signed_value = <int64_t>int(data[long_index])
            raw = <uint64_t>signed_value
            values[i] = <int>((raw >> start) & mask)
    return values


cpdef list count_palette_indices(object data, Py_ssize_t palette_size):
    cdef list counts = [0] * palette_size
    if palette_size <= 0:
        return counts
    if data is None:
        counts[0] = 4096
        return counts

    cdef int bits = _bits_for_palette(palette_size)
    cdef int values_per_long = 64 // bits
    cdef uint64_t mask = (<uint64_t>1 << bits) - 1
    cdef Py_ssize_t long_count = len(data)
    cdef Py_ssize_t i
    cdef Py_ssize_t long_index
    cdef int start
    cdef int64_t signed_value
    cdef uint64_t raw
    cdef int palette_index

    for i in range(4096):
        long_index = i // values_per_long
        palette_index = 0
        if long_index < long_count:
            start = (i % values_per_long) * bits
            signed_value = <int64_t>int(data[long_index])
            raw = <uint64_t>signed_value
            palette_index = <int>((raw >> start) & mask)
        if 0 <= palette_index < palette_size:
            counts[palette_index] += 1
    return counts


cpdef list fill_top_projection(
    list indices,
    list palette,
    list palette_base_names,
    object skip,
    list unresolved,
    list blocks,
):
    cdef list remaining = unresolved
    cdef list next_remaining
    cdef Py_ssize_t palette_len = len(palette)
    cdef Py_ssize_t count
    cdef Py_ssize_t i
    cdef int ly
    cdef int y_offset
    cdef int column
    cdef int palette_index
    cdef object block
    cdef object base_name

    for ly in range(15, -1, -1):
        count = len(remaining)
        if count == 0:
            break
        next_remaining = []
        y_offset = ly << 8
        for i in range(count):
            column = <int>remaining[i]
            palette_index = <int>indices[y_offset | column]
            if 0 <= palette_index < palette_len:
                block = palette[palette_index]
                base_name = palette_base_names[palette_index]
            else:
                block = "minecraft:air"
                base_name = "minecraft:air"
            if base_name in skip:
                next_remaining.append(column)
            else:
                blocks[column] = block
        remaining = next_remaining
    return remaining


cpdef list fill_floor_projection(
    list indices,
    list palette,
    list palette_base_names,
    object skip,
    list unresolved,
    list blocks,
    list heights,
    int section_y,
    int min_y,
    int max_y,
):
    cdef list remaining = unresolved
    cdef list next_remaining
    cdef Py_ssize_t palette_len = len(palette)
    cdef Py_ssize_t count
    cdef Py_ssize_t i
    cdef int ly
    cdef int y
    cdef int y_offset
    cdef int column
    cdef int palette_index
    cdef object block
    cdef object base_name

    for ly in range(15, -1, -1):
        count = len(remaining)
        if count == 0:
            break
        next_remaining = []
        y = section_y * 16 + ly
        if y > max_y:
            continue
        if y < min_y:
            break
        y_offset = ly << 8
        for i in range(count):
            column = <int>remaining[i]
            palette_index = <int>indices[y_offset | column]
            if 0 <= palette_index < palette_len:
                block = palette[palette_index]
                base_name = palette_base_names[palette_index]
            else:
                block = "minecraft:air"
                base_name = "minecraft:air"
            if base_name in skip:
                next_remaining.append(column)
            else:
                blocks[column] = block
                heights[column] = y
        remaining = next_remaining
    return remaining


cpdef list project_template_states(object template_blocks, int width, int height, int size_y, int axis_code):
    cdef Py_ssize_t pixel_count = width * height
    cdef list depths = [-1] * pixel_count
    cdef list states = [-1] * pixel_count
    cdef object block
    cdef object pos
    cdef int px
    cdef int py
    cdef int pz
    cdef int state
    cdef int image_x
    cdef int image_y
    cdef int depth
    cdef Py_ssize_t index

    for block in template_blocks:
        pos = block.get("pos", [0, 0, 0])
        px = <int>int(pos[0])
        py = <int>int(pos[1])
        pz = <int>int(pos[2])
        state = <int>int(block.get("state", 0))
        if axis_code == 0:
            image_x = px
            image_y = pz
            depth = py
        elif axis_code == 1:
            image_x = pz
            image_y = size_y - py - 1
            depth = px
        else:
            image_x = px
            image_y = size_y - py - 1
            depth = pz

        if 0 <= image_x < width and 0 <= image_y < height:
            index = image_y * width + image_x
            if depth >= <int>depths[index]:
                depths[index] = depth
                states[index] = state
    return states


cdef inline int _max_int(int a, int b):
    return a if a > b else b


cdef inline int _min_int(int a, int b):
    return a if a < b else b


cdef inline int _clamp_int(int value, int lower, int upper):
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value


cdef inline int _scaled_length(int src_w, int src_h, int max_w, int max_h, bint width):
    cdef double ratio_w = max_w / <double>src_w
    cdef double ratio_h = max_h / <double>src_h
    cdef double ratio = ratio_w if ratio_w < ratio_h else ratio_h
    cdef int value
    if width:
        value = <int>(src_w * ratio)
    else:
        value = <int>(src_h * ratio)
    if value < 1:
        return 1
    return value


cdef void _fill_rgba(unsigned char[::1] dst, int pixels, int r, int g, int b, int a):
    cdef int i
    cdef Py_ssize_t offset
    for i in range(pixels):
        offset = i * 4
        dst[offset] = <unsigned char>r
        dst[offset + 1] = <unsigned char>g
        dst[offset + 2] = <unsigned char>b
        dst[offset + 3] = <unsigned char>a


cdef inline void _blend_pixel(
    unsigned char[::1] dst,
    Py_ssize_t offset,
    int sr,
    int sg,
    int sb,
    int sa,
):
    cdef int da
    cdef int inv
    cdef int out_a
    if sa <= 0:
        return
    if sa >= 255:
        dst[offset] = <unsigned char>sr
        dst[offset + 1] = <unsigned char>sg
        dst[offset + 2] = <unsigned char>sb
        dst[offset + 3] = <unsigned char>255
        return
    da = dst[offset + 3]
    inv = 255 - sa
    out_a = sa + (da * inv + 127) // 255
    dst[offset] = <unsigned char>((sr * sa + dst[offset] * inv + 127) // 255)
    dst[offset + 1] = <unsigned char>((sg * sa + dst[offset + 1] * inv + 127) // 255)
    dst[offset + 2] = <unsigned char>((sb * sa + dst[offset + 2] * inv + 127) // 255)
    dst[offset + 3] = <unsigned char>out_a


cdef void _draw_scaled_icon(
    const unsigned char[::1] src,
    unsigned char[::1] dst,
    int src_w,
    int src_h,
    int canvas,
    int draw_w,
    int draw_h,
    int off_x,
    int off_y,
    bint flip_x,
    bint flip_y,
):
    cdef int x
    cdef int y
    cdef int sx
    cdef int sy
    cdef Py_ssize_t src_offset
    cdef Py_ssize_t dst_offset
    cdef int sr
    cdef int sg
    cdef int sb
    cdef int sa
    for y in range(draw_h):
        sy = (y * src_h) // draw_h
        if flip_y:
            sy = src_h - sy - 1
        if off_y + y < 0 or off_y + y >= canvas:
            continue
        for x in range(draw_w):
            if off_x + x < 0 or off_x + x >= canvas:
                continue
            sx = (x * src_w) // draw_w
            if flip_x:
                sx = src_w - sx - 1
            src_offset = (sy * src_w + sx) * 4
            sa = src[src_offset + 3]
            if sa == 0:
                continue
            sr = src[src_offset]
            sg = src[src_offset + 1]
            sb = src[src_offset + 2]
            dst_offset = ((off_y + y) * canvas + (off_x + x)) * 4
            _blend_pixel(dst, dst_offset, sr, sg, sb, sa)


cdef void _draw_rotated_icon(
    const unsigned char[::1] src,
    unsigned char[::1] dst,
    int src_w,
    int src_h,
    int canvas,
    int base_w,
    int base_h,
    double radians,
    double y_scale,
    int off_x,
    int off_y,
    bint shadow,
):
    cdef double c = cos(radians)
    cdef double s = sin(radians)
    cdef double center = canvas / 2.0
    cdef double dx
    cdef double dy
    cdef double unscaled_y
    cdef double bx
    cdef double by
    cdef int sx
    cdef int sy
    cdef int x
    cdef int y
    cdef int sr
    cdef int sg
    cdef int sb
    cdef int sa
    cdef Py_ssize_t src_offset
    cdef Py_ssize_t dst_offset
    for y in range(canvas):
        dy = ((y - off_y) - center) / y_scale
        for x in range(canvas):
            dx = (x - off_x) - center
            bx = c * dx + s * dy + base_w / 2.0
            by = -s * dx + c * dy + base_h / 2.0
            if bx < 0 or by < 0 or bx >= base_w or by >= base_h:
                continue
            sx = <int>(bx * src_w / base_w)
            sy = <int>(by * src_h / base_h)
            if sx < 0 or sx >= src_w or sy < 0 or sy >= src_h:
                continue
            src_offset = (sy * src_w + sx) * 4
            sa = src[src_offset + 3]
            if sa == 0:
                continue
            if shadow:
                sr = 28
                sg = 26
                sb = 36
                sa = (sa * 95) // 255
            else:
                sr = src[src_offset]
                sg = src[src_offset + 1]
                sb = src[src_offset + 2]
            dst_offset = (y * canvas + x) * 4
            _blend_pixel(dst, dst_offset, sr, sg, sb, sa)


cpdef bytes render_item_view_rgba(bytes source, int src_w, int src_h, int view_code, int size, tuple background):
    cdef const unsigned char[::1] src = source
    cdef bytearray out = bytearray(size * size * 4)
    cdef unsigned char[::1] dst = out
    cdef int bg_r = <int>background[0]
    cdef int bg_g = <int>background[1]
    cdef int bg_b = <int>background[2]
    cdef int bg_a = <int>background[3]
    cdef int draw_w
    cdef int draw_h
    cdef int off_x
    cdef int off_y
    cdef int depth
    cdef int offset
    cdef double radians
    cdef double y_scale

    if src_w <= 0 or src_h <= 0 or size <= 0:
        return bytes(out)

    _fill_rgba(dst, size * size, bg_r, bg_g, bg_b, bg_a)

    if view_code == 0 or view_code == 1:
        draw_w = _scaled_length(src_w, src_h, size * 78 // 100, size * 78 // 100, True)
        draw_h = _scaled_length(src_w, src_h, size * 78 // 100, size * 78 // 100, False)
        off_x = (size - draw_w) // 2
        off_y = (size - draw_h) // 2
        _draw_scaled_icon(src, dst, src_w, src_h, size, draw_w, draw_h, off_x, off_y, view_code == 1, False)
    elif view_code == 2 or view_code == 3:
        draw_w = _scaled_length(src_w, src_h, _max_int(2, size // 8), size * 72 // 100, True)
        draw_h = _scaled_length(src_w, src_h, _max_int(2, size // 8), size * 72 // 100, False)
        off_x = (size - draw_w) // 2
        off_y = (size - draw_h) // 2
        _draw_scaled_icon(src, dst, src_w, src_h, size, draw_w, draw_h, off_x, off_y, False, view_code == 2)
    elif view_code == 4 or view_code == 5:
        draw_w = _scaled_length(src_w, src_h, size * 72 // 100, _max_int(2, size // 8), True)
        draw_h = _scaled_length(src_w, src_h, size * 72 // 100, _max_int(2, size // 8), False)
        off_x = (size - draw_w) // 2
        off_y = (size - draw_h) // 2
        _draw_scaled_icon(src, dst, src_w, src_h, size, draw_w, draw_h, off_x, off_y, view_code == 5, False)
    else:
        draw_w = _scaled_length(src_w, src_h, size * 62 // 100, size * 62 // 100, True)
        draw_h = _scaled_length(src_w, src_h, size * 62 // 100, size * 62 // 100, False)
        if view_code == 6:
            radians = 0.7853981633974483
            y_scale = 0.58
            depth = _max_int(2, size // 18)
        else:
            radians = -0.4886921905584123
            y_scale = 0.78
            depth = _max_int(3, size // 12)
        for offset in range(depth, 0, -1):
            _draw_rotated_icon(src, dst, src_w, src_h, size, draw_w, draw_h, radians, y_scale, offset, offset, True)
        _draw_rotated_icon(src, dst, src_w, src_h, size, draw_w, draw_h, radians, y_scale, 0, 0, False)
    return bytes(out)


cdef inline long _edge_value(int px, int py, int ax, int ay, int bx, int by):
    return <long>(px - bx) * (ay - by) - <long>(ax - bx) * (py - by)


cdef inline bint _inside_triangle(
    int px,
    int py,
    int x0,
    int y0,
    int x1,
    int y1,
    int x2,
    int y2,
):
    cdef long d1 = _edge_value(px, py, x0, y0, x1, y1)
    cdef long d2 = _edge_value(px, py, x1, y1, x2, y2)
    cdef long d3 = _edge_value(px, py, x2, y2, x0, y0)
    cdef bint has_neg = d1 < 0 or d2 < 0 or d3 < 0
    cdef bint has_pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (has_neg and has_pos)


cdef void _draw_quad(
    unsigned char[::1] dst,
    int canvas_w,
    int canvas_h,
    int x0,
    int y0,
    int x1,
    int y1,
    int x2,
    int y2,
    int x3,
    int y3,
    int color,
    int shade,
):
    cdef int min_x = _clamp_int(_min_int(_min_int(x0, x1), _min_int(x2, x3)), 0, canvas_w - 1)
    cdef int max_x = _clamp_int(_max_int(_max_int(x0, x1), _max_int(x2, x3)), 0, canvas_w - 1)
    cdef int min_y = _clamp_int(_min_int(_min_int(y0, y1), _min_int(y2, y3)), 0, canvas_h - 1)
    cdef int max_y = _clamp_int(_max_int(_max_int(y0, y1), _max_int(y2, y3)), 0, canvas_h - 1)
    cdef int r = (((color >> 16) & 255) * shade) // 255
    cdef int g = (((color >> 8) & 255) * shade) // 255
    cdef int b = ((color & 255) * shade) // 255
    cdef int x
    cdef int y
    cdef Py_ssize_t offset
    if max_x < min_x or max_y < min_y:
        return
    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            if _inside_triangle(x, y, x0, y0, x1, y1, x2, y2) or _inside_triangle(x, y, x0, y0, x2, y2, x3, y3):
                offset = (y * canvas_w + x) * 4
                _blend_pixel(dst, offset, r, g, b, 255)


cdef inline int _closeup_index(int width, int depth, int view_code, int rx, int rz):
    cdef int ix
    cdef int iz
    if rx < 0 or rx >= width or rz < 0 or rz >= depth:
        return -1
    if view_code == 1:
        ix = width - rx - 1
        iz = rz
    elif view_code == 2:
        ix = width - rx - 1
        iz = depth - rz - 1
    elif view_code == 3:
        ix = rx
        iz = depth - rz - 1
    else:
        ix = rx
        iz = rz
    return iz * width + ix


cdef inline int _closeup_height(list heights, int width, int depth, int view_code, int rx, int rz):
    cdef int index = _closeup_index(width, depth, view_code, rx, rz)
    if index < 0:
        return -2147483648
    return <int>heights[index]


cpdef bytes render_closeup_map_rgba(
    list heights,
    list colors,
    int width,
    int depth,
    int canvas_w,
    int canvas_h,
    int view_code,
    int scale,
    int vertical_scale,
    int min_y,
    int max_y,
    tuple background,
):
    cdef bytearray out = bytearray(canvas_w * canvas_h * 4)
    cdef unsigned char[::1] dst = out
    cdef int bg_r = <int>background[0]
    cdef int bg_g = <int>background[1]
    cdef int bg_b = <int>background[2]
    cdef int bg_a = <int>background[3]
    cdef int half = _max_int(2, scale)
    cdef int quarter = _max_int(1, scale // 2)
    cdef int margin = half * 2 + 2
    cdef int sentinel = -2147483648
    cdef int total = width + depth - 1
    cdef int layer
    cdef int rx
    cdef int rz
    cdef int index
    cdef int y
    cdef int color
    cdef int cx
    cdef int sy
    cdef int x0
    cdef int y0
    cdef int x1
    cdef int y1
    cdef int x2
    cdef int y2
    cdef int x3
    cdef int y3
    cdef int neighbor
    cdef int drop
    cdef int shade

    if width <= 0 or depth <= 0 or canvas_w <= 0 or canvas_h <= 0:
        return bytes(out)
    _fill_rgba(dst, canvas_w * canvas_h, bg_r, bg_g, bg_b, bg_a)
    view_code = view_code % 4
    for layer in range(total):
        for rx in range(width):
            rz = layer - rx
            if rz < 0 or rz >= depth:
                continue
            index = _closeup_index(width, depth, view_code, rx, rz)
            if index < 0:
                continue
            y = <int>heights[index]
            if y == sentinel:
                continue
            color = <int>colors[index]
            cx = margin + (rx - rz + depth - 1) * half
            sy = margin + (rx + rz) * quarter + (max_y - y) * vertical_scale
            x0 = cx
            y0 = sy
            x1 = cx + half
            y1 = sy + quarter
            x2 = cx
            y2 = sy + quarter * 2
            x3 = cx - half
            y3 = sy + quarter

            neighbor = _closeup_height(heights, width, depth, view_code, rx + 1, rz)
            if neighbor == sentinel:
                neighbor = min_y
            if y > neighbor:
                drop = (y - neighbor) * vertical_scale
                if drop > 0:
                    _draw_quad(dst, canvas_w, canvas_h, x1, y1, x2, y2, x2, y2 + drop, x1, y1 + drop, color, 145)

            neighbor = _closeup_height(heights, width, depth, view_code, rx, rz + 1)
            if neighbor == sentinel:
                neighbor = min_y
            if y > neighbor:
                drop = (y - neighbor) * vertical_scale
                if drop > 0:
                    _draw_quad(dst, canvas_w, canvas_h, x2, y2, x3, y3, x3, y3 + drop, x2, y2 + drop, color, 115)

            shade = 235 + _clamp_int((y - min_y) * 20 // _max_int(1, max_y - min_y + 1), 0, 20)
            _draw_quad(dst, canvas_w, canvas_h, x0, y0, x1, y1, x2, y2, x3, y3, color, shade)
    return bytes(out)
