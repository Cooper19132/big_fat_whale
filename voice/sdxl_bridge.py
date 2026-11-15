#!/usr/bin/env python3
"""SDXL 出图桥（PC 侧，9906）：给本机 ComfyUI 加一条 SDXL 通道。

为什么单独做一条：
  · 现有的 dsh-qwen-paint 插件只构造 Qwen-Image 工作流（unet + qwen3vl clip），
    而二次元/成人向内容用 SDXL 系（Illustrious / PornMaster / WAI）质量高得多；
  · 直接在 ComfyUI 的 /prompt 接口上拼 SDXL 工作流最省事，不依赖插件；
  · 服务器通过 ssh 隧道 -R 9906 调用它。

接口：
  GET  /health
  GET  /models                     列出 checkpoints 里可用的模型
  POST /draw  {prompt, negative, width, height, steps, cfg, seed, model, sampler}
        → {ok, file, path, costSec, seed}
  GET  /image?name=xxx.png         取图（可选）

默认参数（二次元向）：832x1216, steps 28, cfg 5.5, sampler euler_ancestral, scheduler normal
"""
import json
import os
import random
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 9906
COMFY_CANDIDATES = ([os.environ['COMFY_URL']] if os.environ.get('COMFY_URL')
                    else ['http://127.0.0.1:8189', 'http://127.0.0.1:8188'])
COMFY = COMFY_CANDIDATES[0]          # 当前认定的地址，探测后更新
_COMFY_CHECKED_AT = 0.0
_COMFY_TTL = 60.0


def comfy_base():
    """返回还活着的 ComfyUI 地址；候选全挂就退回第一个（让上层报连接错误）。
    每 60 秒最多探测一次，避免每个请求都多打两次。"""
    global COMFY, _COMFY_CHECKED_AT
    if time.time() - _COMFY_CHECKED_AT < _COMFY_TTL:
        return COMFY
    _COMFY_CHECKED_AT = time.time()
    for base in COMFY_CANDIDATES:
        try:
            with urllib.request.urlopen(base + '/system_stats', timeout=3) as r:
                r.read(64)
            if base != COMFY:
                log('comfy 切换 -> ' + base)
            COMFY = base
            return COMFY
        except Exception:
            continue
    return COMFY
CKPT_DIR = r'D:\ComfyUI\ComfyUI\models\checkpoints'
OUT_DIR = os.environ.get('COMFY_OUT') or r'D:\ComfyUI\ComfyUI\output'
DEFAULT_MODEL = 'waiIllustriousSDXL_v160.safetensors'

NEG_DEFAULT = ('lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, '
               'fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, '
               'signature, watermark, username, blurry, artist name')


def log(msg):
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sdxl.log'), 'a', encoding='utf-8') as f:
            f.write(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {msg}\n')
    except Exception:
        pass


def list_models():
    out = []
    if not os.path.isdir(CKPT_DIR):
        return out
    for f in sorted(os.listdir(CKPT_DIR)):
        if f.lower().endswith(('.safetensors', '.ckpt')):
            p = os.path.join(CKPT_DIR, f)
            out.append({'name': f, 'mb': round(os.path.getsize(p) / 1048576)})
    return out


def build_workflow(p):
    """标准 SDXL 工作流：Checkpoint → CLIP 编码 → KSampler → VAE 解码 → SaveImage。"""
    model = p.get('model') or DEFAULT_MODEL
    return {
        '4': {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': model}},
        '6': {'class_type': 'CLIPTextEncode', 'inputs': {'text': p['prompt'], 'clip': ['4', 1]}},
        '7': {'class_type': 'CLIPTextEncode', 'inputs': {'text': p.get('negative') or NEG_DEFAULT, 'clip': ['4', 1]}},
        '5': {'class_type': 'EmptyLatentImage', 'inputs': {
            'width': int(p.get('width') or 832), 'height': int(p.get('height') or 1216), 'batch_size': 1}},
        '3': {'class_type': 'KSampler', 'inputs': {
            'seed': int(p['seed']), 'steps': int(p.get('steps') or 28), 'cfg': float(p.get('cfg') or 5.5),
            'sampler_name': p.get('sampler') or 'euler_ancestral', 'scheduler': 'normal',
            'denoise': 1.0, 'model': ['4', 0], 'positive': ['6', 0], 'negative': ['7', 0],
            'latent_image': ['5', 0]}},
        '8': {'class_type': 'VAEDecode', 'inputs': {'samples': ['3', 0], 'vae': ['4', 2]}},
        '9': {'class_type': 'SaveImage', 'inputs': {'images': ['8', 0], 'filename_prefix': 'sdxl'}},
    }


def api(path, payload=None, timeout=30):
    url = comfy_base() + path
    if payload is None:
        req = urllib.request.Request(url)
    else:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def wait_image(prompt_id, timeout=300):
    """轮询 /history 直到出图。"""
    end = time.time() + timeout
    while time.time() < end:
        try:
            h = api(f'/history/{prompt_id}')
            if prompt_id in h:
                outs = h[prompt_id].get('outputs') or {}
                for node in outs.values():
                    for img in node.get('images') or []:
                        return img
                return None
        except Exception:
            pass
        time.sleep(1.5)
    return None


def draw(payload):
    t0 = time.time()
    prompt = str(payload.get('prompt') or '').strip()
    if not prompt:
        return {'ok': False, 'error': 'prompt 不能为空'}
    models = [m['name'] for m in list_models()]
    if not models:
        return {'ok': False, 'error': f'checkpoints 目录为空：{CKPT_DIR}'}
    model = payload.get('model') or DEFAULT_MODEL
    if model not in models:
        model = models[0]
    seed = int(payload.get('seed') or random.randint(1, 2 ** 31 - 1))
    wf = build_workflow({**payload, 'prompt': prompt, 'model': model, 'seed': seed})
    try:
        resp = api('/prompt', {'prompt': wf, 'client_id': f'dsh-sdxl-{int(time.time())}'}, timeout=60)
    except Exception as e:
        return {'ok': False, 'error': f'提交 ComfyUI 失败：{e}（ComfyUI 没启动？）'}
    pid = resp.get('prompt_id')
    if not pid:
        return {'ok': False, 'error': f'ComfyUI 未返回 prompt_id：{resp}'}
    img = wait_image(pid)
    if not img:
        return {'ok': False, 'error': '出图超时（300 秒）'}
    name = img.get('filename')
    path = os.path.join(OUT_DIR, name) if name else ''
    res = {
        'ok': True, 'file': name, 'path': path, 'seed': seed, 'model': model,
        'costSec': round(time.time() - t0, 1),
        'size': f"{wf['5']['inputs']['width']}x{wf['5']['inputs']['height']}"
    }
    # 需要跨机传图时直接给 base64（服务器读不到 PC 上的文件）
    if payload.get('inline') and path and os.path.isfile(path):
        import base64
        with open(path, 'rb') as f:
            res['b64'] = base64.b64encode(f.read()).decode()
        res['bytes'] = os.path.getsize(path)
    return res


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == '/health':
            try:
                api('/system_stats', timeout=5)
                up = True
            except Exception:
                up = False
            return self._json(200, {'ok': True, 'comfy': up, 'comfyUrl': comfy_base(), 'models': len(list_models())})
        if u.path == '/models':
            return self._json(200, {'ok': True, 'models': list_models(), 'default': DEFAULT_MODEL})
        if u.path == '/image':
            name = (q.get('name') or [''])[0]
            p = os.path.join(OUT_DIR, os.path.basename(name))
            if not os.path.isfile(p):
                return self._json(404, {'ok': False, 'error': '没这张图'})
            with open(p, 'rb') as f:
                data = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except Exception:
                pass
            return
        return self._json(404, {'ok': False, 'error': 'not found'})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path != '/draw':
            return self._json(404, {'ok': False, 'error': 'not found'})
        try:
            n = int(self.headers.get('Content-Length') or 0)
            payload = json.loads(self.rfile.read(n).decode('utf-8') or '{}') if n else {}
        except Exception:
            payload = {}
        try:
            res = draw(payload)
        except Exception as e:
            res = {'ok': False, 'error': str(e)}
        log(f"draw {str(payload.get('prompt'))[:40]} → ok={res.get('ok')} {res.get('file') or res.get('error')}")
        return self._json(200, res)


def main():
    log(f'SDXL 桥启动 :{PORT} ckpt_dir={CKPT_DIR}')
    print(f'[sdxl] http://127.0.0.1:{PORT}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()


if __name__ == '__main__':
    main()
