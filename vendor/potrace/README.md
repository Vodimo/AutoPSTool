# potrace（随仓库分发）

位图描边为矢量曲线的工具，用于生成平滑刀模线。

- 来源：MSYS2 包 `mingw-w64-ucrt-x86_64-potrace 1.16-2`
- 文件：`potrace.exe`、`libpotrace-0.dll`、`zlib1.dll`（其余 `api-ms-win-crt-*` 为 Windows 自带 UCRT，无需分发）
- 许可：potrace 为 GPLv2，源码见 https://potrace.sourceforge.net/ 。本项目通过子进程调用该独立程序，不链接其代码。
- 调用：`app/vectorize.py` 把 `vendor/potrace/` 加入子进程 PATH 后运行 `potrace.exe -s`。
