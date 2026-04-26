# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: initializedcheck=False

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
