# CELLS-SPLIT-CONTRACT

`rich/cells.split_text` 按“显示单元（cell）”位置切串的现状契约说明。
本文档只记录现状，不改一行实现。所有读数均照抄
`.venv/bin/python repro/split_text_outofrange.py` 的实际输出（A–H 一组、
I–V 一组），未做任何手工改写。

- 涉及实现：`rich/cells.py`（`split_text` / `_split_text` / `chop_cells` /
  `set_cell_size` / `split_graphemes`）、`rich/segment.py`（`Segment._split_cells` /
  `Segment.split_cells`）、`rich/_wrap.py`（`chop_cells` 的调用方）。
- 两条内部分路：`split_text` 先跑 `_is_single_cell_widths(text)`（frozenset
  `issuperset`，空串返回 `True`）。
  - 全部单格字符（含空串）→ **ASCII 快路**：直接 Python 切片
    `text[:cell_position], text[cell_position:]`。
  - 含宽字符/集合外字符 → **逐格累加慢路**：`_split_text`，先
    `split_graphemes` 得到 grapheme span 列表，再从一个按比例估算的
    span 下标起步左右扫描。

## 1. 现状读数（原样照抄）

### 1.1 A–H 组

```text
A chop_cells CJK width1 -> ['', '你', '好']
B chop_cells single wide w1 -> ['', '你']
C chop_cells ascii width1 -> ['a', 'b']
D chop_cells 'a你b' width1 -> ['a', '你', 'b']
E split_text beyond end -> ('abc', '')
F split_text wide raised IndexError list index out of range
G set_cell_size wide grow -> '你   ' 5
H set_cell_size wide crop -> '你 ' 3
```

### 1.2 I–V 组（public 入口：ASCII 快路 vs 宽字符慢路）

```text
### split_text boundary rows (public entry: ASCII fast path vs wide slow path)
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

## 2. 越界 / 负数 / 零三档：两条路各给什么

### 2.1 越界（切点 > 总格数）

- ASCII 快路：切片天然夹到末尾，左段整串、右段空串，不抛异常。
  - I `split_text('abc', 3)` → `('abc', '')`（恰好等于长度，同形）。
  - J `split_text('abc', 10)` → `('abc', '')`。
  - T `split_text('', 3)` → `('', '')`，空串经 `_is_single_cell_widths('') == True`
    进快路，`''[:3], ''[3:]` 还是两个空串，所以空串“越界”也安全。
  - 旁证 E：`split_text('abc', 10)` → `('abc', '')`。
- 宽字符慢路：切点一旦超过总格数，`_split_text` 在第一次解引用越界 span 时就
  `IndexError: list index out of range`，没有任何夹取。
  - N `split_text('你好', 10)` → `IndexError: list index out of range`。
  - U `split_text('ab💩', 99)` → `IndexError: list index out of range`。
  - 旁证 F：`split_text('你好', 10)` → `IndexError list index out of range`。

**同档不一致**：J/E/T 安静夹到末尾，N/U/F 直接炸。这就是题目所说的
“纯 ASCII 走切片自然夹到末尾，含宽字符逐格累加一超总格数直接抛 IndexError”。

### 2.2 负数（切点 < 0）

- ASCII 快路：负下标按 Python 序列切片语义解析（**不是**按“cell 偏移”）。
  - K `split_text('abc', -1)` → `('ab', 'c')`：`'abc'[:-1] == 'ab'`，
    `'abc'[-1:] == 'c'`，切点被折算成 `len + (-1) = 2`。
- 宽字符慢路：函数开头 `if cell_position <= 0: return "", text`
  （`rich/cells.py:250`），所有负数统一归零。
  - O `split_text('你好', -1)` → `('', '你好')`，与 P（切点 0）完全同形。

**同档不一致**：同样的 `-1`，K 给 `('ab','c')`，O 给 `('','你好')`。
慢路把负数当 0，快路把负数当“距末端 N 格”。

### 2.3 零（切点 == 0）

- ASCII 快路：L `split_text('abc', 0)` → `('', 'abc')`（空切片 + 整串）。
- 宽字符慢路：P `split_text('你好', 0)` → `('', '你好')`，同样走
  `cell_position <= 0` 提前返回。
- 空串：S `split_text('', 0)` → `('', '')`，快路。

零这一档两条路**恰好一致**（都是 `('', text)`）。

## 3. 慢路“格位 → span 下标”折算公式，以及 N、U 为什么必炸、M、T 为什么安全

记：

- 输入文本的 grapheme span 数为 `S = len(spans)`，每个 span
  `(start, end, cell_size)` 占 `cell_size` 个显示格；
- 全串总格数 `C = cell_length = Σ cell_size`（`split_graphemes` 的第二个返回值）；
- 目标切点为 `p = cell_position`。

`_split_text` 不做边界夹取，而是用比例估算一个初始 span 下标
（`rich/cells.py:255-257`）：

```text
offset  = int( (p / C) * S )          # 猜测的初始 span 下标
left    = Σ cell_size(spans[0:offset])  # 该下标左侧已覆盖的格数
```

随后 while 循环只按 `left` 与 `p` 的大小关系，在 span 区间内做 `±1` 移动，
循环内假定 `0 <= offset <= S`，并直接读 `spans[offset]`
（left < p 分支，`cells.py:266`）或 `spans[offset-1]`
（left > p 分支，`cells.py:272`）。

### 3.1 N（`'你好'`, p=10）必炸

`S=2`（两个宽字符），`C=4`。初始

```text
offset = int((10/4)*2) = int(5) = 5
```

`spans[:5]` 切片被 Python 夹成全部 2 个 span，`left = 4`；接着
`left_size = 4 != 10` 且 `4 < 10`，进入“左侧不够”分支，立即执行
`spans[offset] = spans[5]` → **IndexError**。循环里的 `offset += 1`
只会继续加大下标，永远到不了 10 格，也没有“超过末尾即返回整串”的出口。

### 3.2 U（`'ab💩'`, p=99）必炸

span 为 `a(1) b(1) 💩(2)`，`S=3`，`C=4`。初始

```text
offset = int((99/4)*3) = int(74.25) = 74
```

`left = 4`（切片被夹满），`4 < 99`，首条解引用就是 `spans[74]` →
**IndexError**。只要 `p > C`，比例式给出的 `offset` 就 `>= S`
（当 `p/C > 1` 时 `(p/C)·S > S`，取整后 `≥ S`），而循环在左移之前
就要读 `spans[offset]`，所以**任何 `p > C` 都在第一轮越界，必炸**。
N 与 U 是同一条不变量被破坏：`offset` 被允许超出 `[0, S]`。

### 3.3 M（`'你好'`, p=4）安全

`S=2`，`C=4`，`p=C`。初始 `offset = int((4/4)*2) = 2`，
`left = 4 == p`，命中 `left_size == cell_position` 分支；该分支显式判
`if offset >= len(spans): return text, ""`（`cells.py:260-262`）。
这是慢路**唯一**的“到末端”出口，所以恰好等长的切点 M 返回
`('你好', '')`，安全。注意它靠的是“等于 + 特判”，不是夹取：
`p` 再大 1 格（N）就绕过这个出口直接越界。

### 3.4 T（`''`, p=3）安全

空串在分路口就被判成单格串（`_is_single_cell_widths('')` 为真，
因为空集合是 frozenset 的子集），根本不进慢路；快路 `''[:3], ''[3:]`
得 `('', '')`。所以 T 的安全是“没走到公式”，与 M 的“走到公式但有特判”
是两种不同的安全来源。

### 3.5 附带发现（不在 A–V 读数内，仅供收口参考）

慢路还有一条同位置的雷：当文本走慢路但总格数 `C == 0`
（如整串是零宽的 `'\u200d'`、`'\x00'`），比例式 `p/C` 直接
`ZeroDivisionError`。它与 N/U 一样，都是“慢路开头缺少对 `C` 与 `p`
的界检查”导致的。

## 4. K `('ab','c')` vs O `('','你好')`：是切片语义还是契约缺口

**判断：这是契约缺口（contract gap），不是有意承诺的“切片语义”。**

依据：

1. 函数按“cell position（显示格偏移）”定义自己，不是按 Python 序列下标。
   `split_text`/`_split_text` 的 docstring 都把入参写作
   “`cell_position`: Offset in cells”，并专门承诺“切点落在双宽字符中间时
   换成两个空格”（Q/R/V）。cell 坐标是从左端数的非负列号，没有“距末端”
   的定义。K 出现的 `('ab','c')` 只是快路复用了内建切片、顺带继承了
   Python 负下标语义的副产物。
2. 慢路根本不支持这种语义：`if cell_position <= 0: return "", text`
   （`cells.py:250`）把所有负数（以及 0）统一归零，O 才是与
   “cell 偏移”语义自洽的结果（负列号不存在 → 钳到 0）。
   若“负切点 = 距末端 N 格”是真契约，慢路必须把 `-1` 折算成
   `C-1`，而现在慢路折算成 `0`，两边不可能同时正确。
3. 仓库里真正按 cell 切的那套实现把负数当非法输入，而不是当切片下标：
   `Segment.split_cells` 在入口写了 `assert cut >= 0`
   （`rich/segment.py:168`），然后 ASCII 分支再判 `cut >= len(text)`
   （`segment.py:172`）。这说明代码库对“cell 切点”的预期是
   “非负、且越界要夹”，K 的负下标行为没有被这套预期承认。
4. 现有测试也没把 K 钉死：`tests/test_cells.py` 的 `test_split_text`
   只钉了 `("", -1)`、`("x", -1)` 两个负偏移用例，两者短串下
   “切片语义”和“归零”恰好给出同一个结果（`('', ...)`），
   区分不出两种语义；没有任何宽字符负偏移用例（O 行为未被测试覆盖）。

因此：O（负数归零）符合“cell 偏移”口径；K（`('ab','c')`）是快路实现
细节泄漏出来的、未经承诺也未经测试的切片副作用。两条路对同一输入域
给出不同答案，缺的是一份统一的切点域约定（`cell_position` 是否允许
负数、越界是夹还是抛），而不是“快路本就该有 Python 切片语义”。

## 5. Q、R、V 里的补位空格是哪一层的规矩；三个消费方各在哪一层防越界

### 5.1 补位空格：定义在“按 cell 切分”原语层，不是 grapheme 层、也不是调用方

Q `('你好', 1)` → `(' ', ' 好')`、R `('a你b', 2)` → `('a ', ' b')`、
V `('ab💩cd', 3)` → `('ab ', ' cd')`，共同特征是切点落在一个 2 格宽
grapheme 正中。这时候：

- `split_graphemes`（`cells.py:161` 起）只负责把串切成
  `(start, end, cell_size)` 的 span，宽字符整体是一个 span，它本身
  **不产空格**，也不知道“切点”。
- 空格是“按 cell 切分”这一层的显式产物。`_split_text` 发现
  `left + cell_size > p`（或左侧越过去一格）时，返回
  `text[:start] + " "` 与 `" " + text[end:]`
  （`cells.py:267-268`、`273-274`）：把被切成两半的宽字符整段丢掉，
  左段尾部补 1 个空格、右段头部补 1 个空格。
- 规矩的目的写在 docstring 里：切点在双宽字符中间时，用两个
  单格空格替掉它，使左右两段拼起来的显示宽度仍等于原串宽度
  （一个宽 2 格的字形 = 左右各 1 格空格）。同一条规矩在
  `Segment._split_cells` 里独立实现了一遍
  （`segment.py:139-148`，`out_by == -1/+1` 且该字符 `cell_size==2`
  时各补一个空格），两处 docstring 表述一致。测试也钉住了这条规矩：
  `split_text('💩', 1) == (' ', ' ')`、`('💩x',1) == (' ',' x')`
  等（`tests/test_cells.py` `test_split_text` 表）。

所以补位空格是**切分原语层（`_split_text` / `Segment._split_cells`）
自定的“保显示宽度”规则**：既不在 `split_graphemes`，也不是
`set_cell_size`/`Text.truncate`/渲染层事后补的。`chop_cells` 则明确
**不**采用这条规则（见 5.2），它宁可把整个宽字符推到下一行。

### 5.2 `chop_cells`：在“grapheme 边界行折行”层防越界，天然不越界、不补空格

A–D 的读数：`chop_cells("你好",1) -> ['', '你', '好']`、
`chop_cells("你",1) -> ['', '你']`、`chop_cells("ab",1) -> ['a','b']`、
`chop_cells("a你b",1) -> ['a','你','b']`。

- 快路：列表推导 `text[index:index+width]`（`cells.py:330` 一带），
  用切片，越界自然夹，靠 Python 切片语义兜住。
- 慢路：只对 span 做**前向遍历**（`for start, end, cell_size in spans`），
  不做 `p/C` 比例估算，也就没有任何越界 span 下标可解引用；
  当 `line_size + cell_size > width` 时把整段宽字符推到下一行
  （A/B 开头那个 `''` 就是“第一格放不下整宽字符 → 先出一个空行”）。
- 因为它从不从宽字符中间切，所以它**不补空格**（A/B/D 里没有任何
  空格替位），5.1 的补位规则与它无关。
- 调用方 `rich/_wrap.py:59` 只在 `word_length > width`（单词比整行
  还宽）且 `fold=True` 时才调它，`width` 来自控制台宽度恒为正，
  调用点天然不会给超界切点；`chop_cells` 这一层没有 N/U 式崩溃面。

### 5.3 `set_cell_size`：在入口用“先量后切 + 分支短路”防住越界

读数：G `set_cell_size("你",5) -> '你   '`（补齐到 5 格）、
H `set_cell_size("你好",3) -> '你 '`（裁到 3 格，尾部那个空格就是
5.1 的半宽补位，经 `_split_text` 左段得到）。

它是内部唯一会调慢路 `_split_text` 的地方，但只在“确实需要裁短”时调
（`cells.py:315-323`）：

- `total <= 0` 直接返回 `""`（`cells.py:315`），挡掉负数/零；
- 先 `cell_size = cell_len(text)` 量出真实总格数；
- `cell_size == total` 原样返回；`cell_size < total` 走补空格分支，
  不调慢路；
- 只有 `cell_size > total`（且 `total > 0`）才执行
  `_split_text(text, total)`——此时 `0 < total < cell_size` 是严格的
  内部切分，永远落在 N/U 触发区间之外，也不会碰到 `C==0`
  （`cell_size > total >= 1` 保证 `C >= 1`）。

即 `set_cell_size` 把界检查放在**自己的入口/分发处**（量长 + 三分支
短路），所以它现在不会触发 N/U，也不会触发 3.5 的除零。

### 5.4 `Segment._split_cells`：在慢路开头显式守卫，是仓库里已有的正确范式

`Segment._split_cells`（`rich/segment.py:108` 起）是和 `_split_text`
平行的另一套“按 cell 切”实现，同样有 `pos = int((cut/cell_length)*len(text))`
式比例估算（`segment.py:129`），但它在进估算之前先做了守卫
（`segment.py:124-126`）：

```text
cell_length = segment.cell_length
if cut >= cell_length:
    return segment, _Segment("", style, control)
```

越界切点直接夹成“整段 + 空段”，`pos` 永远不会按超界比例算出越界值；
公共包装 `Segment.split_cells` 再加 `assert cut >= 0`
（`segment.py:168`）和 ASCII 分支的 `cut >= len(text)` 夹取
（`segment.py:172`）。它的半宽补位与 5.1 同规
（`segment.py:139-148`）。

**小结**：三个消费方里，`chop_cells` 靠“只走 grapheme 边界 + 前向遍历”
结构性地不存在越界切点；`set_cell_size` 靠入口量长 + 分支短路，保证
传给 `_split_text` 的切点严格在内；`Segment._split_cells` 靠慢路开头
一句 `cut >= cell_length` 显式夹。**唯独公共 `split_text` 的宽字符慢路
`_split_text` 没有任何界守卫**，N/U 的崩溃正来自这一格空缺。

## 6. 收口结论：界守卫放哪——慢路开头 vs 公共入口分发前统一夹

### 方案 A：守卫补在慢路开头（`_split_text` 内，`split_graphemes` 之后、比例估算之前）

具体形态（仅描述，不改代码）：拿到 `spans, cell_length` 后，对
`cell_position >= cell_length` 返回 `(text, "")`；对
`cell_position <= 0` 维持现有 `("", text)`。现有
`if cell_position <= 0: ...`（`cells.py:250`）就在慢路里，只需在同一层
补齐“上界”这半边，且必须放在 `split_graphemes` 之后——此时 `C` 才
拿得到，同时顺手让 3.5 的 `C==0` 除零也被覆盖（`cell_position >= 0`
且 `C==0` 时归到“到末端”返回）。

- 影响到的现有用例（行为变化面）：只改变**目前会炸**的 N、U（以及 F
  这个等价旁证），从 `IndexError` 变为 `(text, "")`，与 J/E/T 的快路
  越界结果对齐。M 仍走 `offset>=len(spans)` 出口返回 `('你好','')`，
  读数不变；Q、R、V 的补位空格不变；S/T 不进慢路不变。
  `tests/test_cells.py` 现有断言无需改动，只需新增 N/U 这类宽字符越界
  基线（现在测试集里没有它们，这正是缺口存在的原因之一）。
- 热路径代价：零。ASCII 快路在 `split_text` 里直接切片
  （`cells.py:295`），守卫在慢路、且在宽串必做的 `split_graphemes`
  之后，不增加任何额外宽度扫描；宽路径本来就要付出 grapheme 解析成本，
  加一次整数比较可忽略。
- 与既有范式一致：`Segment._split_cells` 已经在慢路开头用
  `if cut >= cell_length` 这么干（`segment.py:124`）；`set_cell_size`
  也是“先拿到真实 cell 长度再决定”的思路。A 等于把同一套不变量补到
  字符串版本上。
- 未覆盖项：它**不**统一 K/O 的负数分歧。`cell_position <= 0` 这半边
  保持现状（O 归零不变），快路的 K 仍是切片负下标。负数契约要另开一个
  决定（要么公共入口把负数定义为非法、要么快路也归零），但那是第 4 节
  的独立议题，不应和“修 N/U 崩溃”捆在一起。

### 方案 B：公共入口分发前统一夹（`split_text` 里，分路之前先把切点归一）

具体形态：在 `split_text` 入口对 `cell_position` 统一做下界/上界夹取
后再分路。下界若按“cell 偏移非负”夹成 0，则上界需要先知道总格数。

- 影响到的现有用例（行为变化面）：
  - 下界夹 0 会改变 K：`split_text('abc', -1)` 将由现在的
    `('ab','c')` 变成 `('', 'abc')`，去和 O 的 `('', '你好')` 对齐。
    这是**可观察的公共行为变更**，即便 `tests/test_cells.py` 没有 K
    形用例能拦住它，也属于把 4 节判为“缺口”的那半边顺手改义。
  - 上界夹取让 J/E 与 N/U/F 统一为 `(text, "")`，N/U 由炸变结果。
  - 若反过来要保留“负数 = 距末端”，就得把宽路 O 改成按 `C+n` 折算，
    同样是公共行为变更且更复杂。
- 热路径代价：不为零。入口处要得到上界就得知道总格数；单格串尚可
  `len(text)` 推得，但只要想在分路前对两类串用一套规则，就会在当前
  “纯切片、零宽度计算”的 ASCII 快路上引入一次额外测量/分支
  （宽串还要与随后的 `split_graphemes` 重复算宽）。`split_text` 是公开
  原语，任何统一处理都按快路调用频率摊到最常见的纯 ASCII 切分上；
  而崩溃只发生在宽字符慢路，让每条 ASCII 调用为一个慢路 bug 付测量费，
  代价与收益不匹配。
- 覆盖缺口：统一夹只能挡住走公共 `split_text` 的人；`set_cell_size`
  这类直接调私有 `_split_text` 的内部消费方（`cells.py:322`）不受入口
  保护（它们目前靠自带前置条件自保）。入口守卫不产生 `_split_text`
  自身的不变量。

### 结论

采用 **方案 A：把界守卫补在慢路 `_split_text` 开头（`split_graphemes`
之后、比例估算之前）**。理由自洽如下：

1. 根因在慢路：N/U 崩在“`p/C` 比例式把 `offset` 推出 `[0,S]` 后立即
   解引用 `spans[offset]`”，这是 `_split_text` 自己的不变量
   （`0 <= p <= C`）未被校验；在不变量被消费的地方补齐最直接。
2. 代价最小：宽路径反正要跑 `split_graphemes`，守卫复用其 `cell_length`，
   不碰零成本 ASCII 热路径，也不重复算宽；方案 B 却要在热路径上新增
   一次测量/分支。
3. 行为面最窄：A 只把“现在必炸”的 N/U/F 变成与快路一致的
   `(text,"")`，M/Q/R/V/S/T 与既有 `test_split_text` 断言全不变；
   方案 B 还会把 K 这类目前有结果（尽管是副产物语义）的公开行为改义。
4. 与仓库现状同构：`Segment._split_cells` 的
   `if cut >= cell_length`（`segment.py:124`）就是“慢路开头守卫”的
   现成先例，A 是让字符串版本与 Segment 版本收敛到同一条防线。
5. 议题切分干净：A 只解决“越界崩溃”（N/U/F，并兼顾 `C==0` 除零）。
   第 4 节的 K/O 负数分歧是独立的契约缺口，应单独决定“负数是否合法”，
   不应借修崩溃在公共入口悄悄改变快路可观察行为；若日后要统一负数语义，
   再在公共入口层面配合 `Segment.split_cells` 的 `assert cut >= 0`
   口径另行处理。

一句话：**崩溃防线就放在慢路开头、贴着 `cell_length` 的来源处；公共
入口的统一夹取只在将来要正式定义“负切点”时才有必要，现在上它既付费于
热路径，又越权改了 K 的可观察行为。**
