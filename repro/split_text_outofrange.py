from rich.cells import chop_cells, set_cell_size, split_text, _split_text, split_graphemes, cell_len

print("A chop_cells CJK width1 ->", repr(chop_cells("你好", 1)))
print("B chop_cells single wide w1 ->", repr(chop_cells("你", 1)))
print("C chop_cells ascii width1 ->", repr(chop_cells("ab", 1)))
print("D chop_cells 'a你b' width1 ->", repr(chop_cells("a你b", 1)))
try:
    print("E split_text beyond end ->", repr(split_text("abc", 10)))
except Exception as e:
    print("E split_text raised", type(e).__name__, e)
try:
    print("F split_text wide beyond ->", repr(split_text("你好", 10)))
except Exception as e:
    print("F split_text wide raised", type(e).__name__, e)
try:
    print("G set_cell_size wide grow ->", repr(set_cell_size("你", 5)), cell_len(set_cell_size("你",5)))
except Exception as e:
    print("G raised", type(e).__name__, e)
try:
    print("H set_cell_size wide crop ->", repr(set_cell_size("你好", 3)), cell_len(set_cell_size("你好",3)))
except Exception as e:
    print("H raised", type(e).__name__, e)
