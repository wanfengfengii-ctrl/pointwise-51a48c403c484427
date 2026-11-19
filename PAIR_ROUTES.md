# 主备路线交班约定

夜班使用实际接纳的固定路网包签发主备单。两路共用同一包和有序实路口端点。走廊停用时，同一条走廊上的任向原路段均受影响。白班可追加归属不同的新修订并重新发包，既有包和已签单据继续按原号领取。

## 登记与交换

`survey.revisions.save_revision(store, junctions, roads, restrictions, *, corridors=None)` 沿用 V1 的返回值和修订号。

- 省略 `corridors` 或传 `None` 时登记无归属的 V1 修订。提供时传入 `(原有向路段号, 物理走廊号)` 二元组序列，用 V1 的非空白名称口径。每条原有向路段恰有一项，零条路可显式提供空序列。缺项、重复路段、未知路段和非法名称均抛 `ValueError`。
- `exchange.publish.publish` 和 `exchange.imports.import_bundle` 保持原签名。有归属的包在原 `payload` 对象中增加 `corridors`，其值为 `[[road_id, corridor_id], ...]`。该字段存在即表示有归属，`null` 无效。无归属包沿用原有载荷字段。清单结构、版本和摘要规则沿用 V1，因此归属参与同一包的绑定。
- 路段号属于完整有向原路段。同一走廊可对应多个路段号，允许方向相反或起终点不同。接纳时按包内原有向路段核对完整归属；通过摘要校验的件也须通过此核对。切幅沿用原片段规则，每个片段占用其原路段所属走廊。重开源库发布时使用固定修订的归属。实件接纳、同件重投与同号异件冲突沿用 V1 规则。

## 签发与领取

`review.issue.issue_pair(catalog, records, bundle_id, start, end)` 返回已提交的主备单。沿用 `BundleCatalog`、`RecordStore` 及各自的 `initialize()`。端点须为该包内两个不同的实路口，按传入方向计算。

路线是连续完成的原有向路段序列。沿用包中的连续三路禁行，人工缝点只接续原链。允许重访实路口，同一路线也可多次经过同一走廊。两路占用的走廊集合须互斥。按原路段的正整数代价精确累计，先最小化两路总价。每对按 `(单路代价, 原路段号序列)` 升序定主备，再在同总价的路线对中按 `(主路原路段号序列, 备路原路段号序列)` 取字典序首项。可全量计算。

主备单返回对象具有以下公开属性。

- `id` 为正整数单号。`request` 为 `ReviewRequest(bundle_id, start, end)`。
- `main` 和 `backup` 均有 `roads`、`corridors`、`cost`。`roads` 是依通行顺序排列的原路段号元组，`corridors` 是该路的 `frozenset[str]`，`cost` 是该路的精确整数代价。按原路段号可在单据所绑实交包中核对完整片段链。
- `total_cost` 为两路代价之和。无可行对时仍提交一张带请求的单据，其 `main`、`backup`、`total_cost` 均为 `None`。

`review.retrieve.retrieve_pair(records, record_id)` 返回同一份主备单，未知主备单号返回 `None`。领取只读已提交快照，无需求解或访问源库。包号合法但未接纳时抛 `KeyError`，无归属的旧包或非法端点抛 `ValueError`。非法声明、非法件或提交失败不留本次新增成果。SQLite 提交错误按原约定传播，解除故障后可再签。原登记、交换、单路签发、按号领取和单路对照继续兼容旧库、旧包和旧单。

## 可运行样例

`pair_cases.py` 提供三组纯输入夹具。构造函数返回 `junctions`、`roads`、`restrictions`、`corridors` 和 `plans`，可直接传入登记和发布。单独运行该文件可用现有实现检查样例切幅和 V1 单路结果。

- `three_branches()` 从 S 到 T 的三条路线是 `(a1,a2,a3)`、`(b1,b2)`、`(c1,c2)`，单价依次为 3、4、5。主路应为 `(b1,b2)`，占 `{P,B-only}`，备路应为 `(c1,c2)`，占 `{Q,C-only}`，合计 9。另存修订，只把 `a2` 改归 `A-private`，新包应签 `(a1,a2,a3)` 和 `(c1,c2)`，合计 8，原单保持 9。
- `forbidden_loop()` 从 S 到 T 禁止连续走 `a,b,c`。单幅和跨幅均应签 `(a,b,d,e,c)` 和 `(z,)`，分别为 5、6，合计 11。`d`、`e` 是同一走廊 `loop` 上的反向路段。跨幅包中 `b` 的原链依次为 `(west,b-west)`、`(east,b-east)`。只把 `z` 改归 `loop` 并另发包，预期签出无路线对。
- `tied_direct()` 的三条直达路 `a`、`b`、`c` 均为 1，签主 `a`、备 `b`。将 `b` 改归 `a` 所属走廊并另发包，签主 `a`、备 `c`。
- 用三支路声明删一项、重复一项或加入未知路段，登记均应拒绝。对含归属的实件删去 `corridors` 内一项，按原清单规则重算摘要，接纳仍应拒绝。旧包仍可签出原单路，申请主备单时应拒绝。可参考 `tests/support.py` 中的延迟外键故障夹具，在实际签单写入处触发提交失败，检查既有单未变且无新单，解除后重试。

沿用根目录的 `.pointwise-runtime.json`。`version` 保持 1，`kind` 保持 `cli`。`setup` 以 argv 列表表示准备命令，`verify` 和 `demo` 各用一组 argv。交付的 `verify` 覆盖全部原回归及新增业务，失败以非零状态退出。`demo` 展示实际断源签发、禁行回绕和重开后按号领取的结果。
