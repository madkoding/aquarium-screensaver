"""Temporal upscaler (TAAU) for moderngl / OpenGL 3.3.

Each frame is rendered at a lower resolution with a sub-pixel camera jitter. This
pass reconstructs a full-resolution image from those jittered samples and from an
exponentially accumulated history that is reprojected with camera and object motion,
so detail that a spatial filter cannot recover builds up over consecutive frames.

    taau = TemporalUpscaler(ctx)
    out_tex = taau.resolve(color, scene, velocity, in_size, out_size, jitter, inv_vp, prev_vp, cam)

`color` is the (jittered) low-resolution frame, `scene` supplies the camera distance in
its alpha channel, `velocity` the previous screen uv of moving objects (alpha 1 there).
"""
import numpy as np
import moderngl

FULLSCREEN_VS = """
#version 330
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    gl_Position = vec4(p * 2.0 - 1.0, 0.9999, 1.0);
}
"""

RESOLVE_FS = """
#version 330
uniform sampler2D u_cur;      // low-res colour, jittered
uniform sampler2D u_scene;    // low-res scene, alpha = distance from the camera
uniform sampler2D u_vel;      // low-res, xy = previous uv, w = 1 for moving objects
uniform sampler2D u_hist;     // full-res history
uniform vec2 u_inSize;
uniform vec2 u_outSize;
uniform vec2 u_jit;           // jitter applied to the low-res frame, in low-res pixels
uniform mat4 u_invVP;         // un-jittered
uniform mat4 u_prevVP;
uniform vec3 u_camPos;
uniform float u_first;
out vec4 o_col;

bool bad3(vec3 c) { return any(isnan(c)) || any(isinf(c)); }

vec3 tap(ivec2 p) {
    p = clamp(p, ivec2(0), ivec2(u_inSize) - 1);
    vec3 c = texelFetch(u_cur, p, 0).rgb;
    return bad3(c) ? vec3(0.0) : c;
}

// Catmull-Rom through five bilinear fetches: keeps the history sharp while it is resampled.
vec3 historyCR(vec2 uv) {
    vec2 pos = uv * u_outSize;
    vec2 c = floor(pos - 0.5) + 0.5;
    vec2 f = pos - c;
    vec2 w0 = f * (-0.5 + f * (1.0 - 0.5 * f));
    vec2 w1 = 1.0 + f * f * (-2.5 + 1.5 * f);
    vec2 w2 = f * (0.5 + f * (2.0 - 1.5 * f));
    vec2 w3 = f * f * (-0.5 + 0.5 * f);
    vec2 w12 = w1 + w2;
    vec2 t12 = (c + w2 / w12) / u_outSize;
    vec2 t0 = (c - 1.0) / u_outSize;
    vec2 t3 = (c + 2.0) / u_outSize;
    vec3 r = texture(u_hist, vec2(t12.x, t0.y)).rgb * (w12.x * w0.y)
           + texture(u_hist, vec2(t0.x, t12.y)).rgb * (w0.x * w12.y)
           + texture(u_hist, t12).rgb * (w12.x * w12.y)
           + texture(u_hist, vec2(t3.x, t12.y)).rgb * (w3.x * w12.y)
           + texture(u_hist, vec2(t12.x, t3.y)).rgb * (w12.x * w3.y);
    float wsum = w12.x * w0.y + w0.x * w12.y + w12.x * w12.y + w3.x * w12.y + w12.x * w3.y;
    return max(r / wsum, 0.0);
}

void main() {
    vec2 ouv = gl_FragCoord.xy / u_outSize;
    vec2 t = ouv * u_inSize - u_jit;              // where this output pixel falls among the jittered samples (the +jitter shifts the image by -jitter)
    ivec2 c = ivec2(floor(t));
    vec2 fr = t - vec2(c);

    vec3 sum = vec3(0.0), m1 = vec3(0.0), m2 = vec3(0.0), mn = vec3(1e9), mx = vec3(-1e9);
    float wsum = 0.0;
    float best = 1e9;
    ivec2 bp = clamp(c, ivec2(0), ivec2(u_inSize) - 1);
    for (int j = -1; j <= 1; j++) {
        for (int i = -1; i <= 1; i++) {
            ivec2 p = c + ivec2(i, j);
            vec3 col = tap(p);
            vec2 d = vec2(float(i), float(j)) + 0.5 - fr;
            float w = exp(-1.2 * dot(d, d));
            sum += col * w; wsum += w;
            m1 += col; m2 += col * col; mn = min(mn, col); mx = max(mx, col);
            ivec2 q = clamp(p, ivec2(0), ivec2(u_inSize) - 1);
            float dist = texelFetch(u_scene, q, 0).a;
            if (i == 0 && j == 0 && dist > 0.0) { best = dist; bp = q; }      // nearest texel only: dilating snaps silhouettes to the low-res grid
        }
    }
    vec3 cur = sum / max(wsum, 1e-5);
    vec3 mu = m1 / 9.0;
    vec3 sd = sqrt(max(m2 / 9.0 - mu * mu, 0.0));
    vec3 pad = 0.15 * (mx - mn) + 0.5 * sd;
    vec3 lo = min(mn - pad, cur);              // box over the whole window, a little wider than the samples
    vec3 hi = max(mx + pad, cur);

    // reproject: camera motion from the closest surface in the window, object motion from the velocity buffer
    vec4 w = u_invVP * vec4(ouv * 2.0 - 1.0, 1.0, 1.0);
    vec3 dir = normalize(w.xyz / w.w - u_camPos);
    float dist = best < 1e8 ? best : 120.0;
    vec4 pc = u_prevVP * vec4(u_camPos + dir * dist, 1.0);
    vec2 puv = pc.xy / pc.w * 0.5 + 0.5;
    vec4 vel = texelFetch(u_vel, bp, 0);
    if (vel.a > 0.5) { puv = vel.xy; pc.w = 1.0; }

    bool valid = u_first < 0.5 && pc.w > 0.0 && all(greaterThan(puv, vec2(0.0))) && all(lessThan(puv, vec2(1.0)));
    vec3 hist = valid ? historyCR(puv) : cur;
    if (bad3(hist)) { valid = false; hist = cur; }
    vec3 clipped = clamp(hist, lo, hi);

    float motion = length((puv - ouv) * u_outSize);                  // output pixels
    float a = 0.35 + clamp(motion * 0.05, 0.0, 0.4);                  // favour the new frame when moving
    float rejected = length(hist - clipped) / (length(hist) + 0.05);
    a = max(a, clamp(rejected, 0.0, 0.3));
    o_col = vec4(valid ? mix(clipped, cur, a) : cur, 1.0);
}
"""


class TemporalUpscaler:
    def __init__(self, ctx):
        self.ctx = ctx
        self.prog = ctx.program(vertex_shader=FULLSCREEN_VS, fragment_shader=RESOLVE_FS)
        self.vao = ctx.vertex_array(self.prog, [])
        self._size = None
        self._i = 0
        self._targets = []
        self.first = True

    def _alloc(self, size):
        if self._size == tuple(size):
            return
        self._targets = []
        for _ in range(2):
            tex = self.ctx.texture(tuple(size), 4, dtype="f2")
            tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            tex.repeat_x = tex.repeat_y = False
            self._targets.append((tex, self.ctx.framebuffer(color_attachments=[tex])))
        self._size = tuple(size)
        self.first = True

    def resolve(self, color, scene, velocity, in_size, out_size, jitter, inv_vp, prev_vp, cam_pos):
        """Returns the texture holding this frame's full-resolution result."""
        ctx = self.ctx
        self._alloc(out_size)
        hist_tex = self._targets[self._i][0]
        out_tex, out_fbo = self._targets[1 - self._i]
        ctx.disable(moderngl.BLEND)
        ctx.disable(moderngl.DEPTH_TEST)
        out_fbo.use()
        ctx.viewport = (0, 0, out_size[0], out_size[1])
        color.use(0)
        scene.use(1)
        velocity.use(2)
        hist_tex.use(3)
        p = self.prog
        for name, unit in (("u_cur", 0), ("u_scene", 1), ("u_vel", 2), ("u_hist", 3)):
            p[name].value = unit
        p["u_inSize"].value = (float(in_size[0]), float(in_size[1]))
        p["u_outSize"].value = (float(out_size[0]), float(out_size[1]))
        p["u_jit"].value = (float(jitter[0]), float(jitter[1]))
        p["u_invVP"].write(np.ascontiguousarray(inv_vp.T, dtype="f4").tobytes())
        p["u_prevVP"].write(np.ascontiguousarray(prev_vp.T, dtype="f4").tobytes())
        p["u_camPos"].value = tuple(float(v) for v in cam_pos)
        p["u_first"].value = 1.0 if self.first else 0.0
        self.vao.render(moderngl.TRIANGLES, vertices=3)
        self.first = False
        self._i = 1 - self._i
        return out_tex
