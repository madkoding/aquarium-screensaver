"""AMD FidelityFX Super Resolution 1.0 (EASU + RCAS) for moderngl / OpenGL 3.3.

A standalone, reusable port: it only needs a moderngl context and a texture.

    fsr = FSR(ctx)
    fsr.upscale(src_tex, (src_w, src_h), dst_fbo, (dst_w, dst_h), sharpness=0.2)

Pipeline (as in the original): EASU (edge adaptive spatial upsampling) scales
the image, then RCAS (robust contrast adaptive sharpening) restores contrast.
Feed it a *display-referred* image (already tone mapped, roughly perceptual).

Ported from AMD's ffx_fsr1.h / ffx_a.h (FidelityFX-FSR, v1.20210629):
https://github.com/GPUOpen-Effects/FidelityFX-FSR
The algorithm and constants are AMD's; the GLSL here is a scalar 32-bit port
that replaces textureGather with texelFetch so it runs on plain GL 3.3.

----------------------------------------------------------------------------
FidelityFX Super Resolution Sample

Copyright (c) 2021 Advanced Micro Devices, Inc. All rights reserved.
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files(the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and / or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions :
The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
----------------------------------------------------------------------------
"""
import moderngl

FULLSCREEN_VS = """
#version 330
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
"""

# ---------------------------------------------------------------------- EASU
# Layout of the 12-tap kernel around 'f' (F = integer texel of f):
#      b c
#    e f g h
#    i j k l
#      n o
EASU_FS = """
#version 330
uniform sampler2D u_src;
uniform vec2 u_inSize;      // size of the input image, in pixels
uniform vec2 u_outSize;     // size of the output image, in pixels
out vec4 o_col;

// AMD's cheap reciprocal / reciprocal-sqrt approximations (bit tricks).
float aprxLoRcp(float a) { return uintBitsToFloat(0x7ef07ebbu - floatBitsToUint(a)); }
float aprxLoRsq(float a) { return uintBitsToFloat(0x5f347d74u - (floatBitsToUint(a) >> 1u)); }
float sat1(float x) { return clamp(x, 0.0, 1.0); }

vec3 fetch(ivec2 p) {       // clamp-to-edge texel fetch
    return texelFetch(u_src, clamp(p, ivec2(0), ivec2(u_inSize) - 1), 0).rgb;
}
float luma2(vec3 c) { return c.b * 0.5 + (c.r * 0.5 + c.g); }   // luma * 2

// Filtering for a given tap (approximated Lanczos2 with a negative lobe).
void easuTap(inout vec3 aC, inout float aW, vec2 off, vec2 dir, vec2 len,
             float lob, float clp, vec3 c) {
    vec2 v;
    v.x = off.x * dir.x + off.y * dir.y;          // rotate by the edge direction
    v.y = off.x * -dir.y + off.y * dir.x;
    v *= len;                                     // anisotropy
    float d2 = min(v.x * v.x + v.y * v.y, clp);   // limit to the window
    float wB = 2.0 / 5.0 * d2 - 1.0;
    float wA = lob * d2 - 1.0;
    wB *= wB;
    wA *= wA;
    wB = 25.0 / 16.0 * wB - (25.0 / 16.0 - 1.0);
    float w = wB * wA;
    aC += c * w;
    aW += w;
}

// Accumulate edge direction and length for one of the 4 bilinear quadrants.
void easuSet(inout vec2 dir, inout float len, float w,
             float lA, float lB, float lC, float lD, float lE) {
    float dc = lD - lC;
    float cb = lC - lB;
    float lenX = max(abs(dc), abs(cb));
    lenX = aprxLoRcp(lenX);
    float dirX = lD - lB;
    dir.x += dirX * w;
    lenX = sat1(abs(dirX) * lenX);
    lenX *= lenX;
    len += lenX * w;
    float ec = lE - lC;
    float ca = lC - lA;
    float lenY = max(abs(ec), abs(ca));
    lenY = aprxLoRcp(lenY);
    float dirY = lE - lA;
    dir.y += dirY * w;
    lenY = sat1(abs(dirY) * lenY);
    lenY *= lenY;
    len += lenY * w;
}

void main() {
    vec2 ip = floor(gl_FragCoord.xy);
    vec2 scale = u_inSize / u_outSize;
    vec2 pp = ip * scale + (0.5 * scale - 0.5);   // position of 'f' in input pixels
    vec2 fp = floor(pp);
    pp -= fp;
    ivec2 F = ivec2(fp);

    vec3 b = fetch(F + ivec2( 0, -1));
    vec3 c = fetch(F + ivec2( 1, -1));
    vec3 e = fetch(F + ivec2(-1,  0));
    vec3 f = fetch(F);
    vec3 g = fetch(F + ivec2( 1,  0));
    vec3 h = fetch(F + ivec2( 2,  0));
    vec3 i = fetch(F + ivec2(-1,  1));
    vec3 j = fetch(F + ivec2( 0,  1));
    vec3 k = fetch(F + ivec2( 1,  1));
    vec3 l = fetch(F + ivec2( 2,  1));
    vec3 n = fetch(F + ivec2( 0,  2));
    vec3 o = fetch(F + ivec2( 1,  2));

    float bL = luma2(b), cL = luma2(c), eL = luma2(e), fL = luma2(f), gL = luma2(g);
    float hL = luma2(h), iL = luma2(i), jL = luma2(j), kL = luma2(k), lL = luma2(l);
    float nL = luma2(n), oL = luma2(o);

    // Accumulate for bilinear interpolation.
    vec2 dir = vec2(0.0);
    float len = 0.0;
    easuSet(dir, len, (1.0 - pp.x) * (1.0 - pp.y), bL, eL, fL, gL, jL);
    easuSet(dir, len,        pp.x  * (1.0 - pp.y), cL, fL, gL, hL, kL);
    easuSet(dir, len, (1.0 - pp.x) *        pp.y , fL, iL, jL, kL, nL);
    easuSet(dir, len,        pp.x  *        pp.y , gL, jL, kL, lL, oL);

    // Normalize with approximation, and clean up close to zero.
    vec2 dir2 = dir * dir;
    float dirR = dir2.x + dir2.y;
    bool zro = dirR < 1.0 / 32768.0;
    dirR = aprxLoRsq(dirR);
    dirR = zro ? 1.0 : dirR;
    dir.x = zro ? 1.0 : dir.x;
    dir *= vec2(dirR);
    len = len * 0.5;
    len *= len;
    float stretch = (dir.x * dir.x + dir.y * dir.y) * aprxLoRcp(max(abs(dir.x), abs(dir.y)));
    vec2 len2 = vec2(1.0 + (stretch - 1.0) * len, 1.0 - 0.5 * len);
    float lob = 0.5 + ((1.0 / 4.0 - 0.04) - 0.5) * len;
    float clp = aprxLoRcp(lob);

    // Accumulation mixed with min/max of the 4 nearest (de-ringing).
    vec3 min4 = min(min(min(f, g), j), k);
    vec3 max4 = max(max(max(f, g), j), k);
    vec3 aC = vec3(0.0);
    float aW = 0.0;
    easuTap(aC, aW, vec2( 0.0, -1.0) - pp, dir, len2, lob, clp, b);
    easuTap(aC, aW, vec2( 1.0, -1.0) - pp, dir, len2, lob, clp, c);
    easuTap(aC, aW, vec2(-1.0,  1.0) - pp, dir, len2, lob, clp, i);
    easuTap(aC, aW, vec2( 0.0,  1.0) - pp, dir, len2, lob, clp, j);
    easuTap(aC, aW, vec2( 0.0,  0.0) - pp, dir, len2, lob, clp, f);
    easuTap(aC, aW, vec2(-1.0,  0.0) - pp, dir, len2, lob, clp, e);
    easuTap(aC, aW, vec2( 1.0,  1.0) - pp, dir, len2, lob, clp, k);
    easuTap(aC, aW, vec2( 2.0,  1.0) - pp, dir, len2, lob, clp, l);
    easuTap(aC, aW, vec2( 2.0,  0.0) - pp, dir, len2, lob, clp, h);
    easuTap(aC, aW, vec2( 1.0,  0.0) - pp, dir, len2, lob, clp, g);
    easuTap(aC, aW, vec2( 1.0,  2.0) - pp, dir, len2, lob, clp, o);
    easuTap(aC, aW, vec2( 0.0,  2.0) - pp, dir, len2, lob, clp, n);

    // Normalize and de-ring.
    o_col = vec4(min(max4, max(min4, aC * (1.0 / aW))), 1.0);
}
"""

# ---------------------------------------------------------------------- RCAS
RCAS_FS = """
#version 330
uniform sampler2D u_src;
uniform float u_sharp;      // exp2(-stops): 1 = maximum sharpness
uniform float u_dither;     // optional dither amplitude in 1/255 units (0 = off)
uniform float u_grain;      // optional film grain amplitude (0 = off)
uniform float u_time;
out vec4 o_col;

const float FSR_RCAS_LIMIT = 0.25 - 1.0 / 16.0;   // the limit of natural-looking sharpening

float aprxMedRcp(float a) {
    float b = uintBitsToFloat(0x7ef19fffu - floatBitsToUint(a));
    return b * (-b * a + 2.0);
}
vec3 fetch(ivec2 p) {
    return texelFetch(u_src, clamp(p, ivec2(0), textureSize(u_src, 0) - 1), 0).rgb;
}
float hash12(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

void main() {
    ivec2 sp = ivec2(gl_FragCoord.xy);
    //    b
    //  d e f
    //    h
    vec3 b = fetch(sp + ivec2( 0, -1));
    vec3 d = fetch(sp + ivec2(-1,  0));
    vec3 e = fetch(sp);
    vec3 f = fetch(sp + ivec2( 1,  0));
    vec3 h = fetch(sp + ivec2( 0,  1));

    // Min and max of the ring.
    vec3 mn4 = min(min(min(b, d), f), h);
    vec3 mx4 = max(max(max(b, d), f), h);
    // Limiters (high precision reciprocals; epsilon guards pure black).
    vec3 hitMin = min(mn4, e) / max(4.0 * mx4, vec3(1e-6));
    vec3 hitMax = (1.0 - max(mx4, e)) / min(4.0 * mn4 - 4.0, vec3(-1e-6));
    vec3 lobeC = max(-hitMin, hitMax);
    float lobe = max(-FSR_RCAS_LIMIT, min(max(lobeC.r, max(lobeC.g, lobeC.b)), 0.0)) * u_sharp;
    // Resolve, with the medium precision reciprocal to avoid tonality changes.
    float rcpL = aprxMedRcp(4.0 * lobe + 1.0);
    vec3 pix = (lobe * b + lobe * d + lobe * h + lobe * f + e) * rcpL;
    pix += (hash12(gl_FragCoord.xy) - 0.5) * (u_dither / 255.0);
    pix += (hash12(gl_FragCoord.xy * 1.37 + fract(u_time * 7.0) * 131.0) - 0.5) * u_grain * 0.06
         * (1.0 - 0.6 * clamp(dot(pix, vec3(0.3, 0.59, 0.11)), 0.0, 1.0));
    o_col = vec4(pix, 1.0);
}
"""


class FSR:
    """EASU + RCAS as two fullscreen passes. Create once per moderngl context."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.easu = ctx.program(vertex_shader=FULLSCREEN_VS, fragment_shader=EASU_FS)
        self.rcas = ctx.program(vertex_shader=FULLSCREEN_VS, fragment_shader=RCAS_FS)
        self.vao_easu = ctx.vertex_array(self.easu, [])
        self.vao_rcas = ctx.vertex_array(self.rcas, [])
        self._mid = None          # (texture, framebuffer) for the EASU result
        self._mid_size = None

    def _target(self, size):
        if self._mid_size != tuple(size):
            tex = self.ctx.texture(tuple(size), 4, dtype="f2")
            tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            tex.repeat_x = tex.repeat_y = False
            self._mid = (tex, self.ctx.framebuffer(color_attachments=[tex]))
            self._mid_size = tuple(size)
        return self._mid

    def upscale(self, src_tex, src_size, dst_fbo, dst_size, sharpness=0.2, dither=0.0,
                grain=0.0, time=0.0):
        """Scale `src_tex` (src_size) into `dst_fbo` (dst_size).

        sharpness is in stops: 0.0 = maximum sharpening, larger = softer
        (AMD's default is 0.2). dither adds +/- dither/2 of 1/255 at the end.
        """
        ctx = self.ctx
        ctx.disable(moderngl.BLEND)
        ctx.disable(moderngl.DEPTH_TEST)
        mid_tex, mid_fbo = self._target(dst_size)

        mid_fbo.use()
        ctx.viewport = (0, 0, dst_size[0], dst_size[1])
        src_tex.use(0)
        self.easu["u_src"].value = 0
        self.easu["u_inSize"].value = (float(src_size[0]), float(src_size[1]))
        self.easu["u_outSize"].value = (float(dst_size[0]), float(dst_size[1]))
        self.vao_easu.render(moderngl.TRIANGLES, vertices=3)

        dst_fbo.use()
        ctx.viewport = (0, 0, dst_size[0], dst_size[1])
        mid_tex.use(0)
        self.rcas["u_src"].value = 0
        self.rcas["u_sharp"].value = float(2.0 ** (-sharpness))
        self.rcas["u_dither"].value = float(dither)
        self.rcas["u_grain"].value = float(grain)
        self.rcas["u_time"].value = float(time)
        self.vao_rcas.render(moderngl.TRIANGLES, vertices=3)
