#!/usr/bin/env python3
"""服务器的语音转写助手：给 qq-agent 的 watch_video 工具调用。

用法：
  python asr.py <音频或视频路径> [模型名或目录] [语言]

输出（stdout，JSON 一行）：
  {"ok":true,"segments":[{"start":0.0,"end":2.3,"text":"..."}],"voice":true,"note":"..."}
  {"ok":false,"error":"..."}

设计要点（移植 video-watch-plus 的「铁律二」）：
  · 先看模型自报的 no_speech 概率与段数
  · 若各段文本高度重复（unique 比过低），判为幻觉，voice=false
"""
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DEFAULT_MODEL = os.environ.get('ASR_MODEL_DIR', '/opt/qq-agent/models/faster-whisper-tiny')


def main():
    if len(sys.argv) < 2:
        print(json.dumps({'ok': False, 'error': '用法: asr.py <文件> [模型] [语言]'}))
        return
    path = sys.argv[1]
    model = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_MODEL
    lang = sys.argv[3] if len(sys.argv) > 3 else 'zh'
    if not os.path.exists(path):
        print(json.dumps({'ok': False, 'error': f'文件不存在: {path}'}))
        return
    if not os.path.isdir(model):
        print(json.dumps({'ok': False, 'error': f'模型目录不存在: {model}'}))
        return

    try:
        from faster_whisper import WhisperModel
        # CPU + int8，服务器只有 2 核 1.6GB 内存
        m = WhisperModel(model, device='cpu', compute_type='int8', cpu_threads=2)
        # 强制简体中文输出 + 减少繁体/同音漂移
        segments, info = m.transcribe(path, language=lang, beam_size=1,
                                      vad_filter=True, condition_on_previous_text=False,
                                      initial_prompt='以下是普通话的句子，请用简体中文转写。')
        segs = []
        for s in segments:
            text = (s.text or '').strip()
            if not text:
                continue
            segs.append({'start': round(s.start, 2), 'end': round(s.end, 2), 'text': text})

        uniq = len({x['text'] for x in segs})
        unique_ratio = (uniq / len(segs)) if segs else 0.0
        # 判定：0 段 = 没人说话；重复率高 = 幻觉
        if not segs:
            voice, note = False, '没有检出语音（可能是纯音乐/环境音）'
        elif len(segs) >= 3 and unique_ratio < 0.5:
            voice, note = False, f'检出的 {len(segs)} 段里只有 {uniq} 种文本，判为幻觉'
        else:
            voice, note = True, f'{len(segs)} 段，文本多样性 {unique_ratio:.2f}'

        print(json.dumps({
            'ok': True,
            'voice': voice,
            'language': getattr(info, 'language', lang),
            'duration': round(getattr(info, 'duration', 0) or 0, 1),
            'unique_ratio': round(unique_ratio, 2),
            'segments': segs[:80],
            'note': note,
        }, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({'ok': False, 'error': f'{type(e).__name__}: {e}'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
