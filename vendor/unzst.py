#!/usr/bin/env python3
"""把 .tar.zst 拆成 .tar（Windows 没装 zstd CLI 时用）。
用法: python vendor/unzst.py vendor/qq-3.2.34-53644-2026-11-12.tar.zst [输出.tar]
"""
import sys, os
import zstandard as zs

src = sys.argv[1]
dst = sys.argv[2] if len(sys.argv) > 2 else src[:-4]
dctx = zs.ZstdDecompressor()
total = 0
with open(src, 'rb') as fi, open(dst, 'wb') as fo:
    r = dctx.stream_reader(fi, read_size=1 << 20)
    while True:
        chunk = r.read(1 << 20)
        if not chunk:
            break
        fo.write(chunk)
        total += len(chunk)
        if total % (100 << 20) < (1 << 20):
            print(f'  {total >> 20} MB', flush=True)
print(f'完成: {dst}  {total/1048576:.0f} MB')
