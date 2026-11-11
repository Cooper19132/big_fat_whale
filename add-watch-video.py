#!/usr/bin/env python3
"""给小鲸鱼加「真的能看视频」：watch_video 工具。

流程（服务器本地，CPU）：
  1) 定位视频：B站 BV/链接 → 拿 360p 直链；或 QQ 视频消息 → 本地文件
  2) ffprobe 量时长，ffmpeg 抽 6 帧（给视觉）
  3) ffmpeg 抽 16k 单声道音轨 → asr.py（faster-whisper tiny）转写
  4) 返回：帧图（模型能看到）+ 转写文本（带时间戳）
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s = open(P, encoding='utf-8').read()

TOOL = r'''    {
      name: 'watch_video',
      description: '看视频并说出来讲了什么：给 B站 BV 号/链接，或 QQ 里那条视频消息的 #数字。会抽画面帧（你能看到）+ 转写语音（带时间戳）。别人发视频说"看看这个/这视频讲什么"时用它。限制：只处理 6 分钟以内的视频；转写用的是本地小模型，专有名词可能听错，引用前先看画面。',
      parameters: {
        type: 'object',
        properties: {
          target: { type: 'string', description: 'B站 BV 号 / 链接，或 QQ 视频消息的 #数字' },
          frames: { type: 'number', description: '抽几帧（默认 6，最多 10）' }
        },
        required: ['target']
      },
      async execute(ctx, args) {
        const raw = String(args.target || '').trim();
        if (!raw) return err('要看哪个视频？给我 BV 号、链接，或视频消息的 #数字');
        const wantFrames = Math.max(3, Math.min(10, Number(args.frames) || 6));
        const tmpDir = path.join(os.tmpdir(), `watch-${Date.now()}`);
        fs.mkdirSync(tmpDir, { recursive: true });
        let videoPath = '';
        let title = '';
        let meta = [];
        try {
          // ① 来源：B站 还是 QQ 视频消息
          const bili = /^[#]?\d+$/.test(raw) ? null : parseBiliTarget(raw);
          if (bili) {
            const sessdata = String(getConfig().bili?.sessdata || '').trim();
            const biliCookie = String(getConfig().bili?.cookie || '').trim();
            const query = bili.kind === 'bvid' ? `bvid=${bili.value}` : `aid=${bili.value}`;
            const info = await biliGet(`https://api.bilibili.com/x/web-interface/view?${query}`, { sessdata, cookie: biliCookie });
            if (info.code !== 0 || !info.data) return err(`B站返回错误：${info.message || info.code}`);
            const d = info.data;
            title = String(d.title || '');
            const dur = Number(d.duration) || 0;
            if (dur > 360) {
              return ok(`这个视频 ${Math.round(dur / 60)} 分钟，太长了——我只能完整看 6 分钟以内的。要不要我只看开头 3 分钟？（告诉我"看前 3 分钟"）`);
            }
            meta.push(`时长 ${Math.floor(dur / 60)} 分 ${dur % 60} 秒`);
            const play = await biliPlayUrl(d.bvid, d.cid, { sessdata, cookie: biliCookie });
            if (!play?.url) return err('拿不到播放地址（可能需要登录或该视频受限）');
            const res = await fetch(play.url, {
              headers: { 'User-Agent': BILI_UA, Referer: 'https://www.bilibili.com/', ...(biliCookie ? { Cookie: biliCookie } : {}) },
              signal: AbortSignal.timeout(180000)
            });
            if (!res.ok) return err(`视频下载失败 HTTP ${res.status}`);
            const buf = Buffer.from(await res.arrayBuffer());
            if (!buf.length) return err('视频下载为空');
            if (buf.length > 60 * 1024 * 1024) return err(`视频 ${Math.round(buf.length / 1048576)}MB，太大了`);
            videoPath = path.join(tmpDir, 'v.mp4');
            fs.writeFileSync(videoPath, buf);
          } else {
            const entry = ctx.store.findByMid(ctx.chatKey, raw.replace(/^#/, ''));
            if (!entry) return err(`当前会话找不到消息 ${raw}`);
            const src = videoSourceOf(entry.media);
            if (!src) return err('这条消息里没有可读的视频');
            if (src.kind === 'file') {
              videoPath = src.value;
            } else {
              const res = await fetch(src.value, { headers: { 'User-Agent': 'Mozilla/5.0' }, signal: AbortSignal.timeout(180000) });
              if (!res.ok) return err(`视频下载失败 HTTP ${res.status}`);
              const buf = Buffer.from(await res.arrayBuffer());
              videoPath = path.join(tmpDir, 'v.mp4');
              fs.writeFileSync(videoPath, buf);
            }
            title = '（QQ 里的视频）';
          }

          // ② 时长与帧
          let duration = 0;
          try {
            const { stdout } = await execFileP(process.env.FFPROBE_BIN || 'ffprobe',
              ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', videoPath],
              { timeout: 20000 });
            duration = Math.round(parseFloat(String(stdout).trim()) || 0);
          } catch { /* 忽略 */ }
          if (duration > 360) {
            return ok(`这段视频 ${Math.round(duration / 60)} 分钟，超过我一次能看的上限（6 分钟）。`);
          }
          if (duration) meta.push(`实测时长 ${duration} 秒`);

          const dataUrls = await extractVideoFrames({ kind: 'file', value: videoPath }, wantFrames).catch(() => []);

          // ③ 音轨 → ASR
          let transcript = '';
          let voiceInfo = '';
          try {
            const wav = path.join(tmpDir, 'a.wav');
            await execFileP(process.env.FFMPEG_BIN || 'ffmpeg',
              ['-y', '-v', 'error', '-i', videoPath, '-vn', '-ac', '1', '-ar', '16000', wav],
              { timeout: 120000 });
            const py = process.env.ASR_PYTHON || '/opt/qq-agent/.venv-asr/bin/python';
            const script = path.join(ROOT, 'asr.py');
            const { stdout } = await execFileP(py, [script, wav, undefined, 'zh'].filter((x) => x !== undefined),
              { timeout: 600000, maxBuffer: 8 * 1024 * 1024 });
            const j = JSON.parse(String(stdout).trim() || '{}');
            if (j.ok) {
              voiceInfo = j.note || '';
              if (j.voice && j.segments?.length) {
                const lines = j.segments.slice(0, 60).map((x) => {
                  const mm = Math.floor(x.start / 60);
                  const ss = String(Math.round(x.start % 60)).padStart(2, '0');
                  return `${mm}:${ss} ${x.text}`;
                });
                transcript = lines.join('\n');
              }
            } else {
              voiceInfo = `转写不可用：${j.error}`;
            }
          } catch (e) {
            voiceInfo = `转写失败：${e?.message ?? e}`;
          }

          const head = [
            `视频：${title}`,
            meta.length ? `信息：${meta.join('，')}` : '',
            `抽帧：${dataUrls.length} 张（按时间顺序，均匀分布）`,
            voiceInfo ? `语音：${voiceInfo}` : '',
            transcript ? `语音转写（时间戳 分:秒）：\n${transcript}` : '语音：没有可用的转写（可能没人说话，或模型太小吃力）',
            '',
            '注意：帧只能看画面，转写可能有同音错字；**两者对不上时以画面为准**，拿不准就说"这个我说不准"。'
          ].filter(Boolean).join('\n');

          if (dataUrls.length) return { content: imageParts(head, dataUrls) };
          return ok(head);
        } catch (error) {
          return err(`看视频失败：${error?.message ?? error}`);
        } finally {
          try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch { /* 忽略 */ }
        }
      }
    },
'''

anchor = "    {\n      name: 'gpu_tts',"
assert s.count(anchor) == 1, 'gpu_tts 锚点不符'
s = s.replace(anchor, TOOL + anchor, 1)
open(P, 'w', encoding='utf-8').write(s)
print('✓ 已加入 watch_video 工具')
