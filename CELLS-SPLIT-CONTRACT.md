# CELLS-SPLIT-CONTRACT — `split_text` 越界行为现状契约

本文只记录现状、归因与收口建议,**不改动任何实现代码**。
读数来源:仓库根目录执行 `.venv/bin/python repro/split_text_outofrange.py`(rich 15.0.0,工作区基线 `9afeb45`)。
涉及实现:`rich/cells.py` 的 `split_text` / `_split_text` / `chop_cells` / `set_cell_size`,`rich/segment.py` 的 `Segment.split_cells` / `Segment._split_cells`。

## 1. 两条路的分发

`split_text`(rich/cells.py:279)先过 `_is_single_cell_widths`:

- **快路(纯 ASCII / 全单格字符)**:直接 `text[:cell_position], text[cell_position:]`(rich/cells.py:294-295)。Python 切片天然容忍越界与负下标,永不抛异常。
- **慢路(含宽字符 / emoji)**:`_split_text`(rich/cells.py:235)按 grapheme span 逐格累加,用列表下标定位切点,越界即 `IndexError`。

空串是特例:`_is_single_cell_widths("")` 为真(空集是任何集合的子集),空串永远走快路。

## 2. 现状读数(照抄 repro 输出)

### A–H:相邻 API 组

```
A chop_cells CJK width1 -> ['', '你', '好']
B chop_cells single wide w1 -> ['', '你']
C chop_cells ascii width1 -> ['a', 'b']
D chop_cells 'a你b' width1 -> ['a', '你', 'b']
E split_text beyond end -> ('abc', '')
F split_text wide raised IndexError list index out of range
G set_cell_size wide grow -> '你   ' 5
H set_cell_size wide crop -> '你 ' 3
```

### I–V:`split_text` 边界组(公共入口:ASCII 快路 vs 宽字符慢路)

```
I  exact-end ascii     split_text('abc', 3) -> ('abc', '')
J  beyond ascii        split_text('abc', 10) -> ('abc', '')
K  minus1 ascii        split_text('abc', -1) -> ('ab', 'c')
L  zero ascii          split_text('abc', 0) -> ('', 'abc')
M  exact-end wide      split_text('你好', 4) -> ('你好', '')
N  beyond wide         split_text('你好', 10) -> IndexError: list index out of range
O  minus1 wide         split_text('你好', -1) -> ('', '你好')
P  zero wide           split_text('你好', 0) -> ('', '你好')
Q  mid-grapheme wide   split_text('你好', 1) -> (' ', ' 好')
R  mixed ascii+wide    split_text('a你b', 2) -> ('a ', ' b')
S  empty, 0            split_text('', 0) -> ('', '')
T  empty beyond        split_text('', 3) -> ('', '')
U  emoji beyond        split_text('ab💩', 99) -> IndexError: list index out of range
V  emoji mid           split_text('ab💩cd', 3) -> ('ab ', ' cd')
```

## 3. 三档对照:越界 / 负数 / 零

| 档位 | 快路(纯 ASCII) | 慢路(含宽字符) |
| --- | --- | --- |
| 越界(切点 > 总格数) | 自然夹到末尾:J `('abc', '')`;E 同 | **抛 `IndexError: list index out of range`**:N、U;F 同 |
| 负数切点 | 按 Python 负下标从尾部数:K `('ab', 'c')` | 一律视为 0:O `('', '你好')` |
| 零 | L `('', 'abc')` | P `('', '你好')`,两路一致 |
| 恰好末尾(参照) | I `('abc', '')` | M `('你好', '')`,两路一致 |
| 空串(参照,只走快路) | S `('', '')`、T `('', '')` | 不可达 |

即:零和恰好末尾两路一致;越界和负数两路分叉,越界是"夹紧 vs 抛异常",负数是"从尾数 vs 归零"。

## 4. 慢路的"格位 → 下标"折算公式,与 N/U 必炸、M/T 安全的原因

`_split_text` 先用 `split_graphemes` 把字符串切成 `spans`(每个 grapheme 一条 `(start, end, cell_size)`)并算出总格数 `cell_length`,然后(rich/cells.py:253-254):

```python
offset    = int((cell_position / cell_length) * len(spans))   # 初始猜测下标
left_size = sum(map(_span_get_cell_len, spans[:offset]))      # 猜测点左侧的累计格数
```

随后 while 循环按 `left_size` 与 `cell_position` 的差逐格修正 `offset ±1`。关键:**只有 `left_size == cell_position` 分支里有 `offset >= len(spans)` 的兜底**(rich/cells.py:259-261);`left_size < cell_position` 分支直接 `spans[offset]` 取下标(rich/cells.py:265),没有任何边界检查。

- **N(`'你好'`, 10)必炸**:`cell_position=10 > cell_length=4`,初始 `offset = int(10/4*2) = 5 ≥ len(spans)=2`,`left_size = 4 < 10`,进入 `<` 分支读 `spans[5]` → 当场 `IndexError`。退一万步,即使初始猜测落在界内,`left_size` 的上限就是 `cell_length`,永远追不上 `cell_position`,循环只会把 `offset` 一格一格推出列表末尾。所以**任何 `cell_position > cell_length` 都必然 `IndexError`**,与猜测公式无关。U(`'ab💩'`, 99)同理:`offset = int(99/4*3) = 74 ≥ 3`,首迭代即炸。
- **M(`'你好'`, 4)安全**:`cell_position == cell_length` 时 `offset = int(4/4*2) = 2 = len(spans)`,`left_size = 4 == cell_position`,恰好走进唯一有 `offset >= len(spans)` 兜底的分支,返回 `(text, '')`。"恰好末尾"是唯一被接住的越界相邻情形。
- **T(`''`, 3)安全**:空串被 `_is_single_cell_widths` 判为纯单格,根本不进慢路;快路 `''[:3], ''[3:]` 得 `('', '')`。S 同理。

## 5. K 与 O 的不一致:切片语义还是契约缺口?

**判断:契约缺口,不是值得保留的"切片语义"。**

依据:

1. 参数契约是"以显示格为单位的偏移量"(docstring:`cell_position Offset in cells`),其定义域是 `[0, cell_len]`。负切点对两条路都在定义域之外,不存在"快路实现了另一种合法语义"的说法。
2. 慢路在 rich/cells.py:250-251 有显式的 `cell_position <= 0` 归一化,返回 `('', text)`——这是库自己写下的、对域外输入的唯一成文规定。
3. 快路的 K 行 `('ab', 'c')` 不是设计出来的语义,是 `text[:cell_position]` 把 Python 负下标切片原样漏了出来——因为切片不抛异常,所以从来没人需要给它写守卫。
4. 两条路只是 `_is_single_cell_widths` 上的性能分发,对同一输入本应可互换;同一输入产生可观测的分叉,按定义就是契约缺口。何况 K 的 `-1 → 从尾数一格` 与 O 的 `-1 → 归零` 互相矛盾,二者不可能同时是"对的语义"。

## 6. 补位空格是哪层的规矩;三个消费方各自在哪层防越界

**补位规矩的归属**:被切开的半个宽字符替换成空格,是 **cells 层 `_split_text` 自己定的规矩**,写在 rich/cells.py:266-267 与 272-273 的 `return text[:start] + " ", " " + text[end:]`——左右各补一个空格,保证 `cell_len(左) + cell_len(右) == cell_len(原文)` 的显示宽度守恒。Q(`(' ', ' 好')`)、R(`('a ', ' b')`)、V(`('ab ', ' cd')`)的空格都来自这两行。`Segment._split_cells` 在 segment 层独立复刻了同一条规矩(rich/segment.py:139-150)。`chop_cells`、`set_cell_size` 都不参与定义这条规矩。

**三个消费方的越界防线**:

- **`chop_cells`(rich/cells.py:326)**:结构性免疫,无需守卫。它不做任何"格位 → 下标"换算,只遍历 spans 累加 `line_size`,超宽就在宽字符**之前**断行(宁可行短也不切字符),所以 B 行 `chop_cells('你', 1)` 得 `['', '你']` 而不是抛异常或补空格。`width` 只影响断点位置,永远不会变成非法下标。
- **`set_cell_size`(rich/cells.py:299)**:在自己这层预夹。`total <= 0` 提前返回 `''`(cells.py:312-313);只有 `cell_size > total` 时才调 `_split_text`(cells.py:322),即入参被压进 `0 < total < cell_len` 的安全区间,`_split_text` 永远收不到越界值。G(填充)、H(裁切)不炸靠的就是这层预夹。
- **`Segment._split_cells`(rich/segment.py:108)**:在自己这层入口夹。先做 `cut >= cell_length` 直接返回 `(segment, Segment(''))`(segment.py:122-123),再进入与 `_split_text` 同类的逐格循环;公共包装 `split_cells` 另有 `assert cut >= 0`(segment.py:172)和单格快路自带的 `cut >= len(text)` 判断(segment.py:174-175)。这条热路径(`Segment.divide` → `Text.divide` → wrap/render)因此从不把越界切点交给 cells 层。

## 7. 收口结论:界守卫补在哪

两个候选位置:

**方案一:慢路开头补守卫(`_split_text` 内,`split_graphemes` 之后)。**
形如 `if cell_position >= cell_length: return text, ''`,与已有的 `cell_position <= 0` 守卫(cells.py:250)对称。

- 现成用例/先例:`Segment._split_cells` 的 `cut >= cell_length` 预夹(segment.py:122-123)和 `set_cell_size` 的调用前预夹(cells.py:322)都是"在知道 `cell_length` 的那一层夹"的同款模式,方案一只是把 segment 层已有的写法下沉到 cells 层,行为上正好让 N/U 对齐 J/E 的 `('原文', '')`。
- 热路径代价:**零额外扫描**。`split_graphemes` 本来就已算出 `cell_length`,守卫只是 O(1) 比较;快路完全不经过这里,`Segment.split_cells` 热路径也不经过 `split_text`,无任何回归面。

**方案二:公共入口 `split_text` 分发前统一夹。**
形如 `cell_position = min(max(cell_position, 0), cell_len(text))` 再分发。

- 现成用例/先例:无。现有代码里没有任何一层在"还不知道总格数"时做夹紧;`set_cell_size`、`Segment._split_cells` 都是先量后夹。
- 热路径代价:夹紧需要 `cell_len(text)`,而宽字符文本量一次格宽就是一遍全扫,随后 `_split_text` 的 `split_graphemes` 还要再扫一遍——**慢路每次调用翻倍扫描**;`set_cell_size` 已保证入参在界内,入口夹对它是纯开销。更糟的是统一夹会顺带改写快路负数行为(K 行从 `('ab', 'c')` 变成 `('', 'abc')`),把"修崩溃"扩大成"改快路语义",回归面反而变大。

**结论:守卫补在慢路开头(方案一)。** 它与 `Segment._split_cells`、`set_cell_size` 两处现有的"先量后夹"先例同构,只花一次 O(1) 比较就把 N/U 对齐到快路的夹紧语义;入口统一夹(方案二)既让慢路热路径付出双倍扫描,又被迫顺手改变快路负数行为,代价与收益不自洽。负数档的 K/O 分叉属契约缺口,可在方案一落地后另行对齐(建议向慢路的"非正即零"归一),不属于本次越界守卫的必备范围。
