"""GLSL 3.30 sources for every pass of the aquarium renderer."""

# Shared by the fragment shaders: water colour, fog, caustics, hashing.
COMMON = """
uniform float u_time;
uniform vec2 u_res;
uniform vec3 u_camPos;
uniform vec3 u_sunDir;     // unit vector pointing TO the light
uniform vec3 u_sunCol;     // light colour * intensity (dim at night)
uniform float u_day;       // 0 night .. 1 day
uniform vec3 u_waterTop;
uniform vec3 u_waterBot;
uniform float u_fog;

vec3 bg_color(vec2 uv) {
    return mix(u_waterBot, u_waterTop, pow(clamp(uv.y, 0.0, 1.0), 1.5));
}

float hash12(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

// Tileable water caustics (classic iterated-sine trick), result in 0..1.
float caustics(vec2 uv, float time) {
    const float TAU = 6.28318530718;
    vec2 p = mod(uv * TAU, TAU) - 250.0;
    vec2 i = p;
    float c = 1.0;
    const float inten = 0.005;
    for (int n = 0; n < 4; n++) {
        float t = time * (1.0 - (3.5 / float(n + 1)));
        i = p + vec2(cos(t - i.x) + sin(t + i.y), sin(t - i.y) + cos(t + i.x));
        c += 1.0 / length(vec2(p.x / (sin(i.x + t) / inten), p.y / (cos(i.y + t) / inten)));
    }
    c /= 4.0;
    c = 1.17 - pow(c, 1.4);
    return clamp(pow(abs(c), 8.0), 0.0, 1.0);
}

// Distance fog: absorbs red first, then dissolves into the background colour.
vec3 apply_fog(vec3 col, vec3 world, vec2 fragUV) {
    float dist = length(u_camPos - world);
    vec3 absorb = exp(-vec3(0.10, 0.04, 0.015) * dist * 0.30);
    float f = 1.0 - exp(-dist * u_fog);
    return mix(col * absorb, bg_color(fragUV), f);
}

vec3 ambient(vec3 N) {
    vec3 up = vec3(0.16, 0.34, 0.50) * (0.25 + 0.75 * u_day);
    vec3 down = vec3(0.03, 0.07, 0.10) * (0.4 + 0.6 * u_day);
    return mix(down, up, N.y * 0.5 + 0.5);
}
"""

# ------------------------------------------------------------- background
FULLSCREEN_VS = """
#version 330
out vec2 uv;
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    uv = p;
    gl_Position = vec4(p * 2.0 - 1.0, 0.9999, 1.0);
}
"""

BG_FS = "#version 330\n" + COMMON + """
in vec2 uv;
out vec4 o_col;
void main() {
    vec3 c = bg_color(uv);
    // faint luminous haze near the surface
    c += u_sunCol * 0.06 * pow(clamp(uv.y, 0.0, 1.0), 4.0);
    o_col = vec4(c, 1.0);
}
"""

# ------------------------------------------------------------------ seabed
FLOOR_VS = """
#version 330
uniform mat4 u_view;
uniform mat4 u_proj;
in vec3 in_pos;
in vec3 in_nrm;
in vec3 in_col;
out vec3 v_world;
out vec3 v_nrm;
out vec3 v_col;
void main() {
    v_world = in_pos;
    v_nrm = in_nrm;
    v_col = in_col;
    gl_Position = u_proj * u_view * vec4(in_pos, 1.0);
}
"""

FLOOR_FS = "#version 330\n" + COMMON + """
in vec3 v_world;
in vec3 v_nrm;
in vec3 v_col;
out vec4 o_col;
void main() {
    vec3 N = normalize(v_nrm);
    vec3 L = normalize(u_sunDir);
    float diff = max(dot(N, L), 0.0);
    float c = caustics(v_world.xz * 0.16, u_time * 0.55);
    float shallow = smoothstep(-6.0, 0.0, v_world.z);   // brighter nearer the glass
    vec3 col = v_col * (ambient(N) + u_sunCol * diff * 0.75)
             + v_col * u_sunCol * c * (0.55 + 0.9 * shallow);
    o_col = vec4(apply_fog(col, v_world, gl_FragCoord.xy / u_res), 1.0);
}
"""

# -------------------------------------------------------------------- fish
FISH_VS = """
#version 330
uniform mat4 u_view;
uniform mat4 u_proj;
in vec3 in_pos;
in vec3 in_nrm;
in vec2 in_uv;
in float in_part;
in vec3 in_pivot;
in vec3 i_pos;
in vec3 i_fwd;
in vec4 i_size;    // length, height factor, thickness factor, unused
in vec4 i_fin;     // tail scale, dorsal scale, pectoral scale, undulation amplitude
in vec4 i_anim;    // swim phase, bend, pattern, unused
in vec3 i_c1;
in vec3 i_c2;
in vec3 i_c3;
out vec3 v_world;
out vec3 v_nrm;
out vec2 v_uv;
out vec3 v_local;
out vec3 v_nloc;
flat out float v_part;
flat out float v_pattern;
flat out float v_sy;
flat out vec3 v_c1;
flat out vec3 v_c2;
flat out vec3 v_c3;

void main() {
    int part = int(in_part + 0.5);
    vec3 p = in_pos;

    float fs = 1.0;
    if (part == 1) fs = i_fin.x;
    else if (part == 2 || part == 4) fs = i_fin.y;
    else if (part == 3) fs = i_fin.z;
    p = in_pivot + (p - in_pivot) * fs;

    if (part == 3) {                       // pectoral fins flap around the body axis
        float side = sign(in_pivot.z);
        float a = sin(i_anim.x * 0.8 + side) * 0.45 * side;
        vec3 d = p - in_pivot;
        float c = cos(a), s = sin(a);
        p = in_pivot + vec3(d.x, d.y * c - d.z * s, d.y * s + d.z * c);
    }

    // A wave travels from head to tail; the tail end swings the most.
    float s = clamp(0.5 - p.x, 0.0, 1.6);
    float w = s * s * (0.35 + 0.65 * s);
    float wave = sin(i_anim.x - s * 5.5);
    float len = i_size.x;
    vec3 local = p * vec3(1.0, i_size.y, i_size.z) * len;
    local.z += (i_fin.w * wave * w * 0.20 + i_anim.y * s * s * 0.45) * len;

    vec3 X = normalize(i_fwd);
    vec3 Z = cross(X, vec3(0.0, 1.0, 0.0));
    Z = normalize(Z + vec3(1e-4, 0.0, 0.0));
    vec3 Y = cross(Z, X);
    vec3 world = i_pos + X * local.x + Y * local.y + Z * local.z;

    vec3 nl = normalize(in_nrm / vec3(1.0, i_size.y, i_size.z));
    v_nrm = X * nl.x + Y * nl.y + Z * nl.z;
    v_world = world;
    v_uv = in_uv;
    v_local = in_pos;
    v_nloc = in_nrm;
    v_part = in_part;
    v_pattern = i_anim.z;
    v_sy = i_size.y;
    v_c1 = i_c1;
    v_c2 = i_c2;
    v_c3 = i_c3;
    gl_Position = u_proj * u_view * vec4(world, 1.0);
}
"""

FISH_FS = "#version 330\n" + COMMON + """
in vec3 v_world;
in vec3 v_nrm;
in vec2 v_uv;
in vec3 v_local;
in vec3 v_nloc;
flat in float v_part;
flat in float v_pattern;
flat in float v_sy;
flat in vec3 v_c1;
flat in vec3 v_c2;
flat in vec3 v_c3;
out vec4 o_col;

float band(float t, float c, float w) { return smoothstep(w, w - 0.012, abs(t - c)); }

vec3 body_color(int pat, float t, float v, out float emis) {
    emis = 0.0;
    float back = smoothstep(-0.25, 0.55, v);
    vec3 col = mix(v_c2, v_c1, back);
    if (pat == 0) {                                   // neon stripe + red rear belly
        float stripe = smoothstep(0.30, 0.06, abs(v - 0.05))
                     * smoothstep(0.08, 0.20, t) * smoothstep(0.95, 0.78, t);
        col = mix(col, vec3(0.9, 0.15, 0.1), smoothstep(0.55, 0.70, t) * smoothstep(0.1, -0.5, v) * 0.9);
        col = mix(col, v_c3, stripe);
        emis = stripe * 0.9;
    } else if (pat == 1) {                            // white-banded, black-edged
        for (int k = 0; k < 3; k++) {
            float c = (k == 0) ? 0.27 : ((k == 1) ? 0.55 : 0.88);
            float w = (k == 0) ? 0.05 : ((k == 1) ? 0.06 : 0.03);
            float d = abs(t - c);
            col = mix(col, v_c3, smoothstep(w + 0.04, w + 0.012, d));
            col = mix(col, vec3(0.96), smoothstep(w, w - 0.014, d));
        }
    } else if (pat == 2) {                            // surgeonfish: dark palette + yellow tail
        float d = abs(v - (0.20 + 0.35 * sin(t * 7.0)));
        float dark = smoothstep(0.35, 0.20, d) * smoothstep(0.15, 0.30, t) * smoothstep(0.95, 0.70, t);
        col = mix(col, v_c3, dark * 0.92);
        col = mix(col, vec3(1.0, 0.82, 0.10), smoothstep(0.80, 0.92, t));
    } else if (pat == 3) {                            // shark: dark back, pale belly
        col = mix(v_c2, v_c1, smoothstep(-0.05, 0.18, v));
        col *= 1.0 - 0.18 * smoothstep(0.012, 0.0, abs(fract((t - 0.23) * 36.0) - 0.5) - 0.44) * step(0.20, t) * step(t, 0.32);
    } else if (pat == 4) {                            // angelfish: tall black bars
        col = mix(v_c2, v_c1, smoothstep(-0.6, 0.6, v));
        col = mix(col, v_c3, band(t, 0.30, 0.045));
        col = mix(col, v_c3, band(t, 0.52, 0.060));
        col = mix(col, v_c3 * 1.5, band(t, 0.86, 0.03));
    } else {                                          // tuna: lateral yellow line
        col = mix(v_c2, v_c1, smoothstep(-0.30, 0.40, v));
        col = mix(col, v_c3, smoothstep(0.10, 0.0, abs(v - 0.05)) * 0.5 * step(0.2, t));
    }
    col *= 0.95 + 0.05 * sin(t * 220.0) * sin(v * 50.0 + t * 60.0);   // scale sheen
    return col;
}

vec3 fin_color(int pat, float along, float outv) {
    vec3 c = mix(v_c1, v_c2, 0.4);
    if (pat == 0) c = vec3(0.75, 0.82, 0.92) * 0.75;
    else if (pat == 1) c = mix(v_c1, v_c3, smoothstep(0.80, 1.0, outv));
    else if (pat == 2) c = (v_part < 1.5) ? vec3(1.0, 0.82, 0.10) : mix(v_c1, v_c3, smoothstep(0.7, 1.0, outv));
    else if (pat == 3) c = v_c1 * 0.8;
    else if (pat == 4) c = mix(v_c1 * 0.9, v_c3, smoothstep(0.55, 1.0, outv));
    else c = (v_part < 2.5) ? v_c1 : vec3(0.95, 0.8, 0.1);
    return c * (0.82 + 0.18 * sin(along * 80.0));
}

void main() {
    vec3 N = normalize(v_nrm);
    int part = int(v_part + 0.5);
    int pat = int(v_pattern + 0.5);
    if (part != 0 && !gl_FrontFacing) N = -N;

    float emis = 0.0;
    vec3 albedo;
    if (part == 0) {
        albedo = body_color(pat, v_uv.x, v_uv.y, emis);
        // eye: ring + pupil on the side-facing flanks
        vec2 e = vec2(v_local.x - 0.375, (v_local.y - 0.03) * v_sy);
        float d = length(e);
        if (abs(v_nloc.z) > 0.35 && v_local.x > 0.30) {
            albedo = mix(albedo, vec3(0.92, 0.82, 0.45), smoothstep(0.034, 0.030, d));
            albedo = mix(albedo, vec3(0.01), smoothstep(0.022, 0.019, d));
            albedo += vec3(1.0) * smoothstep(0.008, 0.004, length(e - vec2(0.006, 0.008)));
        }
    } else {
        albedo = fin_color(pat, v_uv.x, v_uv.y);
    }

    vec3 L = normalize(u_sunDir);
    vec3 V = normalize(u_camPos - v_world);
    float ndl = dot(N, L);
    float diff = max(ndl, 0.0);
    float wrap = max((ndl + 0.6) / 1.6, 0.0);
    vec3 lit = ambient(N) + u_sunCol * (0.55 * diff + 0.35 * wrap);
    vec3 col = albedo * lit;
    col += albedo * u_sunCol * caustics(v_world.xz * 0.16 + v_world.y * 0.05, u_time * 0.55)
         * 0.35 * max(N.y, 0.0);
    vec3 H = normalize(L + V);
    float spec = pow(max(dot(N, H), 0.0), 70.0) * (part == 0 ? 0.55 : 0.12);
    col += spec * u_sunCol;
    float rim = pow(1.0 - max(dot(N, V), 0.0), 3.0);
    col += rim * vec3(0.10, 0.26, 0.36) * (0.4 + 0.6 * u_day);
    col += albedo * emis * 0.9;                       // neon stripes glow (feeds the bloom)

    o_col = vec4(apply_fog(col, v_world, gl_FragCoord.xy / u_res), 1.0);
}
"""

# ----------------------------------------------------------------- seaweed
KELP_VS = """
#version 330
uniform mat4 u_view;
uniform mat4 u_proj;
uniform float u_time;
in vec2 in_uv;       // u along the height, side -1..1
in vec3 i_base;
in vec4 i_dim;       // height, width, phase, yaw
in vec3 i_col;
out vec3 v_world;
out vec3 v_nrm;
out vec3 v_col;
out float v_u;
out float v_side;
void main() {
    float u = in_uv.x;
    float side = in_uv.y;
    float h = i_dim.x;
    float sway = sin(u_time * 0.9 + i_dim.z + u * 2.8) * 0.22
               + sin(u_time * 0.45 + i_dim.z * 1.7 + u * 1.3) * 0.12;
    vec3 lat = vec3(cos(i_dim.w), 0.0, sin(i_dim.w));
    vec3 across = vec3(-lat.z, 0.0, lat.x);
    float amp = u * u * h * 0.45;
    float width = i_dim.y * (1.0 - 0.65 * u) * (0.85 + 0.25 * sin(u * 9.0 + i_dim.z));
    vec3 world = i_base + vec3(0.0, u * h - sway * sway * amp * 0.15, 0.0)
               + across * sway * amp + lat * side * width;
    v_world = world;
    v_nrm = across;
    v_col = i_col;
    v_u = u;
    v_side = side;
    gl_Position = u_proj * u_view * vec4(world, 1.0);
}
"""

KELP_FS = "#version 330\n" + COMMON + """
in vec3 v_world;
in vec3 v_nrm;
in vec3 v_col;
in float v_u;
in float v_side;
out vec4 o_col;
void main() {
    vec3 N = normalize(v_nrm);
    if (!gl_FrontFacing) N = -N;
    vec3 L = normalize(u_sunDir);
    vec3 albedo = v_col * mix(0.62, 1.30, v_u) * (0.88 + 0.12 * smoothstep(0.0, 0.25, abs(v_side)));
    float trans = pow(max(dot(-N, L), 0.0), 1.5) * 0.5;      // light shining through the blade
    vec3 lit = ambient(N) + u_sunCol * (0.45 * abs(dot(N, L)) + trans);
    vec3 col = albedo * lit;
    col += albedo * u_sunCol * caustics(v_world.xz * 0.16 + v_world.y * 0.1, u_time * 0.55) * 0.25;
    o_col = vec4(apply_fog(col, v_world, gl_FragCoord.xy / u_res), 1.0);
}
"""

# --------------------------------------------------------------- jellyfish
JELLY_BELL_VS = """
#version 330
uniform mat4 u_view;
uniform mat4 u_proj;
in vec3 in_pos;
in vec3 in_nrm;
in vec3 i_pos;
in float i_size;
in float i_phase;
in vec3 i_col;
out vec3 v_world;
out vec3 v_nrm;
out vec3 v_col;
out vec3 v_local;
void main() {
    float pulse = sin(i_phase);
    vec3 l = in_pos;
    l.xz *= 1.0 - 0.14 * pulse;
    l.y *= 1.0 + 0.10 * pulse;
    vec3 world = i_pos + l * i_size;
    v_world = world;
    v_nrm = in_nrm;
    v_col = i_col;
    v_local = in_pos;
    gl_Position = u_proj * u_view * vec4(world, 1.0);
}
"""

JELLY_BELL_FS = "#version 330\n" + COMMON + """
in vec3 v_world;
in vec3 v_nrm;
in vec3 v_col;
in vec3 v_local;
out vec4 o_col;
void main() {
    vec3 N = normalize(v_nrm);
    vec3 V = normalize(u_camPos - v_world);
    float fres = pow(1.0 - abs(dot(N, V)), 2.0);
    float veins = 0.5 + 0.5 * sin(atan(v_local.z, v_local.x) * 14.0);
    vec3 glow = v_col * (0.35 + 0.55 * fres + 0.25 * veins * (1.0 - v_local.y));
    vec3 col = apply_fog(glow * (0.55 + 0.45 * u_day) , v_world, gl_FragCoord.xy / u_res);
    float a = 0.20 + 0.55 * fres + 0.12 * veins;
    o_col = vec4(col * a, a);       // premultiplied alpha
}
"""

JELLY_TENT_VS = """
#version 330
uniform mat4 u_view;
uniform mat4 u_proj;
uniform float u_time;
in vec3 in_t;          // u down the tentacle, side, index
in vec3 i_pos;
in float i_size;
in float i_phase;
in vec3 i_col;
out vec3 v_world;
out vec3 v_col;
out float v_u;
void main() {
    float u = in_t.x;
    float k = in_t.z;
    float ang = 6.2831853 * k / 14.0;
    float pulse = sin(i_phase);
    float rim = 0.85 * (1.0 - 0.14 * pulse);
    vec3 top = vec3(cos(ang) * rim, -0.12, sin(ang) * rim);
    float len = 2.3 + 0.8 * fract(sin(k * 12.9898) * 43758.5453);
    vec3 p = top + vec3(0.0, -u * len, 0.0);
    p.x += sin(u_time * 1.4 + u * 5.0 - i_phase * 0.5 + k) * 0.12 * u;
    p.z += cos(u_time * 1.1 + u * 4.0 + k * 1.7) * 0.12 * u;
    vec3 side = vec3(-sin(ang), 0.0, cos(ang)) * in_t.y * 0.018 * (1.0 - 0.6 * u);
    vec3 world = i_pos + (p + side) * i_size;
    v_world = world;
    v_col = i_col;
    v_u = u;
    gl_Position = u_proj * u_view * vec4(world, 1.0);
}
"""

JELLY_TENT_FS = "#version 330\n" + COMMON + """
in vec3 v_world;
in vec3 v_col;
in float v_u;
out vec4 o_col;
void main() {
    float a = (1.0 - v_u) * 0.55;
    vec3 col = apply_fog(v_col * (0.6 + 0.4 * u_day), v_world, gl_FragCoord.xy / u_res);
    o_col = vec4(col * a, a);
}
"""

# ------------------------------------------------- bubbles & marine snow
BUBBLE_VS = """
#version 330
uniform mat4 u_view;
uniform mat4 u_proj;
uniform float u_time;
uniform float u_resy;
uniform float u_floor;
out float v_alpha;
out vec3 v_world;
float h(float x) { return fract(sin(x * 127.1 + 311.7) * 43758.5453); }
void main() {
    const int SRC = 14;
    int id = gl_VertexID;
    float s = float(id % SRC);
    float j = float(id / SRC);
    vec2 src = vec2((h(s) - 0.5) * 26.0, -h(s + 9.0) * 13.0 + 0.5);
    float speed = 0.5 + 0.45 * h(s * 7.0 + j);
    float span = 5.5;
    float period = span / speed;
    float lt = u_time + j * 0.9 + h(j + s * 3.0) * period;
    float k = fract(lt / period);
    float y = u_floor + 0.1 + k * span;
    float x = src.x + sin(lt * 2.1 + j) * 0.07 * (0.3 + k) + k * 0.25;
    vec3 world = vec3(x, y, src.y + sin(lt * 1.3 + j) * 0.05);
    float r = mix(0.014, 0.05, k) * (0.55 + 0.9 * h(j * 2.3 + s));
    vec4 clip = u_proj * u_view * vec4(world, 1.0);
    gl_Position = clip;
    gl_PointSize = max(r * u_proj[1][1] * u_resy / clip.w, 2.0);
    v_alpha = smoothstep(0.0, 0.04, k) * (1.0 - smoothstep(0.92, 1.0, k));
    v_world = world;
}
"""

BUBBLE_FS = "#version 330\n" + COMMON + """
in float v_alpha;
in vec3 v_world;
out vec4 o_col;
void main() {
    vec2 c = gl_PointCoord * 2.0 - 1.0;
    float d = length(c);
    if (d > 1.0) discard;
    float rim = smoothstep(0.62, 0.95, d) * (1.0 - smoothstep(0.95, 1.0, d));
    float hl = smoothstep(0.38, 0.0, length(c - vec2(-0.35, 0.40)));
    float a = (rim * 0.75 + hl * 0.85 + 0.05) * v_alpha;
    vec3 col = vec3(0.75, 0.93, 1.0) * (rim + hl + 0.1) * (0.4 + 0.6 * max(u_day, 0.3));
    float f = 1.0 - exp(-length(u_camPos - v_world) * u_fog);
    o_col = vec4(col * a * (1.0 - f), a * (1.0 - f));
}
"""

SNOW_VS = """
#version 330
uniform mat4 u_view;
uniform mat4 u_proj;
uniform float u_time;
uniform float u_resy;
out float v_alpha;
float h(float x) { return fract(sin(x * 91.7 + 17.3) * 43758.5453); }
void main() {
    float id = float(gl_VertexID);
    vec3 box = vec3((h(id) - 0.5) * 34.0, 0.0, 2.0 - h(id + 5.0) * 17.0);
    float fall = u_time * (0.04 + 0.05 * h(id + 2.0));
    float y = mod(h(id + 1.0) * 7.0 - fall, 7.0) - 3.2;
    vec3 world = vec3(box.x + sin(u_time * 0.2 + id) * 0.25, y, box.z);
    vec4 clip = u_proj * u_view * vec4(world, 1.0);
    gl_Position = clip;
    gl_PointSize = max(0.012 * u_proj[1][1] * u_resy / clip.w, 1.5);
    v_alpha = (0.25 + 0.5 * h(id + 3.0)) * (0.6 + 0.4 * sin(u_time * 0.7 + id));
}
"""

SNOW_FS = "#version 330\n" + COMMON + """
in float v_alpha;
out vec4 o_col;
void main() {
    vec2 c = gl_PointCoord * 2.0 - 1.0;
    float a = smoothstep(1.0, 0.2, length(c)) * v_alpha * 0.55;
    o_col = vec4(vec3(0.6, 0.8, 0.9) * a * (0.4 + 0.6 * u_day), a * 0.6);
}
"""

# ---------------------------------------------------------------- god rays
RAYS_FS = "#version 330\n" + COMMON + """
uniform float u_rays;
in vec2 uv;
out vec4 o_col;
void main() {
    float aspect = u_res.x / u_res.y;
    vec2 p = vec2(uv.x * aspect, uv.y);
    float q = p.x + (1.0 - p.y) * 0.32;
    float sum = 0.0;
    for (int i = 0; i < 18; i++) {
        float fi = float(i);
        float c = (fi + hash12(vec2(fi, 3.0))) / 18.0 * (aspect + 0.6) - 0.3;
        float w = 0.05 + 0.06 * hash12(vec2(fi, 7.0));
        float flick = 0.55 + 0.45 * sin(u_time * (0.25 + 0.2 * hash12(vec2(fi, 1.0))) + fi * 2.1);
        sum += exp(-pow((q - c) / w, 2.0)) * flick;
    }
    float depth = pow(clamp(uv.y, 0.0, 1.0), 1.6);
    float a = sum * depth * u_rays;
    o_col = vec4(u_sunCol * a, a);
}
"""

# -------------------------------------------------------------- post chain
DOWN_FS = """
#version 330
uniform sampler2D u_tex;
uniform vec2 u_texel;
in vec2 uv;
out vec4 o_col;
void main() {   // 4 bilinear taps = a 4x4 box average
    vec3 c = texture(u_tex, uv + u_texel * vec2(-1.0, -1.0)).rgb
           + texture(u_tex, uv + u_texel * vec2( 1.0, -1.0)).rgb
           + texture(u_tex, uv + u_texel * vec2(-1.0,  1.0)).rgb
           + texture(u_tex, uv + u_texel * vec2( 1.0,  1.0)).rgb;
    // keep only the bright parts so the whole sea doesn't haze over
    c *= 0.25;
    float l = max(max(c.r, c.g), c.b);
    o_col = vec4(c * smoothstep(0.45, 1.0, l), 1.0);
}
"""

BLUR_FS = """
#version 330
uniform sampler2D u_tex;
uniform vec2 u_dir;
in vec2 uv;
out vec4 o_col;
void main() {
    vec3 c = texture(u_tex, uv).rgb * 0.2270270;
    c += (texture(u_tex, uv + u_dir * 1.3846154).rgb
        + texture(u_tex, uv - u_dir * 1.3846154).rgb) * 0.3162162;
    c += (texture(u_tex, uv + u_dir * 3.2307692).rgb
        + texture(u_tex, uv - u_dir * 3.2307692).rgb) * 0.0702703;
    o_col = vec4(c, 1.0);
}
"""

FINAL_FS = """
#version 330
uniform sampler2D u_scene;
uniform sampler2D u_bloom1;
uniform sampler2D u_bloom2;
uniform vec2 u_res;
uniform float u_time;
uniform float u_g1;
uniform float u_g2;
uniform float u_vig;
in vec2 uv;
out vec4 o_col;
float hash12(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}
void main() {
    vec3 c = texture(u_scene, uv).rgb
           + texture(u_bloom1, uv).rgb * u_g1
           + texture(u_bloom2, uv).rgb * u_g2;
    vec2 d = (uv - 0.5) * vec2(u_res.x / u_res.y * 0.55, 1.0) * 2.0;
    c *= 1.0 - u_vig * smoothstep(0.55, 1.6, length(d));
    c = c / (1.0 + 0.12 * c);                    // gentle highlight roll-off
    c += (hash12(gl_FragCoord.xy + fract(u_time) * 91.0) - 0.5) / 255.0;   // de-band gradients
    o_col = vec4(c, 1.0);
}
"""
