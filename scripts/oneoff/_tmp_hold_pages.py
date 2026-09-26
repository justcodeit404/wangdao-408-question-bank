import json
from pathlib import Path

files = {
    "ds": Path(r"C:\Users\16416\Desktop\考研\apps\bank-408\output\questions.json"),
    "coa": Path(r"C:\Users\16416\Desktop\考研\apps\bank-408\output\questions_coa.json"),
    "net": Path(r"C:\Users\16416\Desktop\考研\apps\bank-408\output\questions_net.json"),
    "os": Path(r"C:\Users\16416\Desktop\考研\apps\bank-408\output\questions_os.json"),
}
out = {}
for key, path in files.items():
    data = json.loads(path.read_text(encoding="utf-8"))
    for ch in data["chapters"]:
        name = ch.get("name") or ""
        for q in ch.get("questions") or []:
            uid = f"408:cs408-{key}::{name}::{q['id']}"
            out[uid] = q

wanted = [
    "408:cs408-ds::线性表 · 线性表的顺序表示 · 选择题::X03",
    "408:cs408-ds::线性表 · 线性表的链式表示 · 选择题::X13",
    "408:cs408-ds::排序 · 交换排序 · 选择题::X11",
    "408:cs408-coa::总线 · 总线概述 · 选择题::X07",
    "408:cs408-os::进程与线程 · CPU调度 · 选择题::X37",
    "408:cs408-net::应用层 · 文件传输协议 · 选择题::X11",
    "408:cs408-net::应用层 · 电子邮件 · 选择题::X05",
    "408:cs408-coa::计算机系统概述 · 计算机的性能指标 · 选择题::X11",
    "408:cs408-coa::数据的表示和运算 · 运算方法和运算电路 · 选择题::X23",
    "408:cs408-coa::存储系统 · 高速缓冲存储器 · 选择题::X19",
    "408:cs408-coa::指令系统 · 寻址方式 · 选择题::X23",
    "408:cs408-coa::中央处理器 · 数据通路的功能和基本结构 · 选择题::X15",
    "408:cs408-net::应用层 · 文件传输协议 · 选择题::X03",
]
for uid in wanted:
    q = out.get(uid)
    if not q:
        print("MISSING", uid)
        continue
    print(uid)
    a_pages = q.get("a_pages") or []
    print("  page", q.get("page"), "q_pages", q.get("q_pages"), "a_pages[:8]", a_pages[:8], "n", len(a_pages))
    print("  bbox", q.get("bbox"))
