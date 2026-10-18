"""GLSL 3.30 sources for every pass of the aquarium renderer."""


# Water-surface waves and sea-floor height, shared by the caustic vertex shader
# and every fragment shader (so CPU and GPU agree on the same ocean).
WAVES = """
uniform float u_surf;
uniform float u_floor;

float floor_h(vec2 p) {
    return u_floor + 0.16 * sin(p.x * 0.33 + p.y * 0.21)
         + 0.10 * sin(p.x * 0.87 - p.y * 0.53 + 1.3)
         + 0.06 * sin(p.y * 0.9 + p.x * 0.2);
}

// detail 1 = all wave trains, 0 = only the long swell (used far from the camera)
float surf_h_lod(vec2 p, float t, float detail) {
    float h = 0.060 * sin(dot(p, vec2( 0.9,  0.4)) * 1.7 - t * 1.1)
            + 0.045 * sin(dot(p, vec2(-0.5,  0.8)) * 2.3 - t * 1.5 + 1.3)
            + detail * (0.030 * sin(dot(p, vec2( 0.2, -1.0)) * 3.1 - t * 1.9 + 2.1)
                      + 0.026 * sin(dot(p, vec2(-0.7, -0.6)) * 2.9 - t * 1.7 + 0.4))
            + detail * detail * (0.018 * sin(dot(p, vec2( 1.0,  0.1)) * 5.3 - t * 2.6 + 0.7)
                               + 0.014 * sin(dot(p, vec2( 0.3,  0.95)) * 4.1 - t * 2.2 + 2.6));
    return u_surf + h;
}

float surf_h(vec2 p, float t) { return surf_h_lod(p, t, 1.0); }

vec3 surf_normal_lod(vec2 p, float t, float detail) {
    const float e = 0.02;
    float dx = surf_h_lod(p + vec2(e, 0.0), t, detail) - surf_h_lod(p - vec2(e, 0.0), t, detail);
    float dz = surf_h_lod(p + vec2(0.0, e), t, detail) - surf_h_lod(p - vec2(0.0, e), t, detail);
    return normalize(vec3(-dx, 2.0 * e, -dz));
}

vec3 surf_normal(vec2 p, float t) { return surf_normal_lod(p, t, 1.0); }
"""

# Shared by the fragment shaders: water colour, fog, caustics, hashing.
COMMON = WAVES + """
uniform float u_time;
uniform float u_irid;         // 0/1 fish iridescence switch (settings 'iridescence')
uniform vec2 u_res;
uniform vec3 u_camPos;
uniform vec3 u_sunDir;     // unit vector pointing TO the light
uniform vec3 u_sunCol;     // light colour * intensity (dim at night)
uniform float u_day;       // 0 night .. 1 day
uniform vec3 u_waterTop;
uniform vec3 u_waterBot;
uniform float u_fog;
uniform float u_photo;              // 0..1 photographic look: water absorption, grade, filmic curve

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
    vec3 absorb = exp(-vec3(0.10, 0.04, 0.015) * dist * 0.30 * (1.0 + 1.1 * u_photo));
    float f = 1.0 - exp(-dist * u_fog * (1.0 + 0.18 * u_photo));
    vec3 haze = bg_color(fragUV);
    haze = mix(haze, vec3(dot(haze, vec3(0.30, 0.59, 0.11))) * vec3(0.80, 1.00, 0.97), 0.30 * u_photo);   // murkier, a touch green
    return mix(col * absorb, haze, f);
}

vec3 amb_t(float t) {
    vec3 up = vec3(0.16, 0.34, 0.50) * (0.40 + 0.60 * u_day);
    vec3 down = vec3(0.03, 0.07, 0.10) * (0.55 + 0.45 * u_day);
    return mix(down, up, t);
}
vec3 ambient(vec3 N) { return amb_t(N.y * 0.5 + 0.5); }
"""

# Ray-tracing helpers (appended to COMMON): ellipsoid occluders, sun-space grid
# shadows and the refraction-based caustic map.
RT_COMMON = """
uniform float u_rt;                 // 1 = ray-traced effects on
uniform float u_gi;                 // probe-grid indirect light strength, 0 = off
uniform sampler2D u_grid;           // occluder ids per sun-space cell (R32F)
uniform sampler2D u_occ;            // occluder ellipsoids (RGBA32F, 4 rows)
uniform sampler2D u_caus;           // caustic flux on the sea floor plane (R16F)
uniform sampler2D u_mirror;         // traced underside of the water surface
uniform vec2 u_gridOrigin;
uniform float u_cell;
uniform ivec2 u_gridDim;
uniform int u_nocc;
uniform int u_nstatic;
uniform vec2 u_mapOrigin;
uniform vec2 u_mapSize;
uniform vec3 u_refr;                // refracted sun direction (unit, y < 0)
uniform float u_cgain;
const int GRID_K = 12;

struct Occ {
    vec3 c; vec3 X; vec3 Y; vec3 Z; vec3 r; float opac; float soft; vec3 col;
};

Occ load_occ(int id) {
    vec4 a = texelFetch(u_occ, ivec2(id, 0), 0);
    vec4 b = texelFetch(u_occ, ivec2(id, 1), 0);
    vec4 c = texelFetch(u_occ, ivec2(id, 2), 0);
    vec4 d = texelFetch(u_occ, ivec2(id, 3), 0);
    Occ o;
    o.c = a.xyz;
    o.X = normalize(b.xyz);
    vec3 Z = normalize(cross(o.X, vec3(0.0, 1.0, 0.0)) + vec3(1e-4, 0.0, 0.0));
    o.Z = Z;
    o.Y = cross(Z, o.X);
    o.r = vec3(a.w, b.w, c.x);
    o.soft = (c.y < 0.5) ? 5.0 : ((c.y < 1.5) ? 3.0 : 4.0);
    o.opac = c.z;
    o.col = d.rgb;
    return o;
}

// Soft shadow of one ellipsoid on a ray (after the classic sphere soft shadow,
// evaluated in the ellipsoid's unit-sphere space). 1 = lit, 0 = dark.
float occ_soft(Occ o, vec3 ro, vec3 rd) {
    vec3 d = ro - o.c;
    vec3 lo = vec3(dot(d, o.X), dot(d, o.Y), dot(d, o.Z)) / o.r;
    vec3 ld = vec3(dot(rd, o.X), dot(rd, o.Y), dot(rd, o.Z)) / o.r;
    ld = normalize(ld);
    float b = dot(lo, ld);
    float c = dot(lo, lo) - 1.0;
    float h = b * b - c;
    float dd = sqrt(max(0.0, 1.0 - h)) - 1.0;
    float t = -b - sqrt(max(h, 0.0));
    float v = (t < 0.0) ? 1.0 : smoothstep(0.0, 1.0, 2.5 * o.soft * dd / t);
    return mix(1.0, v, o.opac);
}

// Shadow ray from p toward the light. Only the occluders registered in the
// ray's sun-space cell are tested (the grid is the acceleration structure).
float rt_shadow(vec3 p, vec3 L, int skip) {
    if (u_rt < 0.5) return 1.0;
    vec2 q = p.xz - L.xz * (p.y / L.y);
    ivec2 c = ivec2(floor((q - u_gridOrigin) / u_cell));
    if (c.x < 0 || c.y < 0 || c.x >= u_gridDim.x || c.y >= u_gridDim.y) return 1.0;
    float vis = 1.0;
    for (int k = 0; k < GRID_K; k++) {
        float idf = texelFetch(u_grid, ivec2(c.x * GRID_K + k, c.y), 0).r;
        if (idf < 0.0) break;
        int id = int(idf + 0.5);
        if (id == skip) continue;
        vec3 oc = p - texelFetch(u_occ, ivec2(id, 0), 0).xyz;
        float rmax = texelFetch(u_occ, ivec2(id, 3), 0).w;
        float b = dot(oc, L);
        float margin = rmax + 0.12 * max(-b, 0.0) + 0.05;       // penumbra grows with distance
        if ((b > 0.0 && dot(oc, oc) > rmax * rmax) || dot(oc, oc) - b * b > margin * margin) continue;
        vis *= occ_soft(load_occ(id), p, L);
    }
    return vis;
}

// Light flux at p from the caustic map: follow the refracted sun ray from p
// down to the floor plane and read what landed there. About 1 on average.
float rt_flux(vec3 p, float lod) {
    float t = (u_floor - p.y) / u_refr.y;
    vec2 q = p.xz + u_refr.xz * t;
    vec2 uv = (q - u_mapOrigin) / u_mapSize;
    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) return 1.0;
    return textureLod(u_caus, uv, lod).r * u_cgain;
}

// Sunlight fades with depth below the surface (ray-traced mode only).
float sun_atten(vec3 p) {
    return mix(1.0, exp(-max(u_surf - p.y, 0.0) * 0.08), u_rt);
}

uniform sampler2D u_wgrid;          // occluder ids per world cell, for AO rays (R32F)
uniform vec2 u_wgridOrigin;
uniform float u_wcell;
uniform ivec2 u_wgridDim;
uniform float u_frame;
const int WGRID_K = 14;

float ell_hit(Occ o, vec3 ro, vec3 rd, out vec3 n) {
    vec3 d = ro - o.c;
    vec3 lo = vec3(dot(d, o.X), dot(d, o.Y), dot(d, o.Z)) / o.r;
    vec3 ld = vec3(dot(rd, o.X), dot(rd, o.Y), dot(rd, o.Z)) / o.r;
    float a = dot(ld, ld);
    float b = dot(lo, ld);
    float c = dot(lo, lo) - 1.0;
    float disc = b * b - a * c;
    n = vec3(0.0, 1.0, 0.0);
    if (disc < 0.0) return -1.0;
    float t = (-b - sqrt(disc)) / a;
    if (t <= 0.0) return -1.0;
    vec3 pl = (lo + ld * t) / o.r;
    n = normalize(o.X * pl.x + o.Y * pl.y + o.Z * pl.z);
    return t;
}


vec3 cosine_dir(vec3 N, vec2 xi) {
    float r = sqrt(xi.x);
    float a = 6.2831853 * xi.y;
    vec3 T = normalize(abs(N.y) < 0.99 ? cross(N, vec3(0.0, 1.0, 0.0)) : cross(N, vec3(1.0, 0.0, 0.0)));
    vec3 B = cross(N, T);
    return normalize(T * (r * cos(a)) + B * (r * sin(a)) + N * sqrt(max(1.0 - xi.x, 0.0)));
}

// Ambient occlusion: ONE random cosine-weighted ray per pixel per frame, traced
// against the occluders near p. The TAA pass averages the frames into a smooth result.
float rt_ao(vec3 p, vec3 N, int skip) {
    if (u_rt < 0.5) return 1.0;
    vec2 xi = vec2(hash12(gl_FragCoord.xy + u_frame * 7.13), hash12(gl_FragCoord.yx * 1.7 + u_frame * 3.91));
    vec3 d = cosine_dir(N, xi);
    const float maxd = 1.5;
    // The ray is shorter than a cell, so it only visits the cell of p and the
    // cell of its far end; every occluder touching it is registered in one of them.
    ivec2 cA = ivec2(floor((p.xz - u_wgridOrigin) / u_wcell));
    ivec2 cB = ivec2(floor(((p + d * maxd).xz - u_wgridOrigin) / u_wcell));
    float ao = 1.0;
    for (int pass = 0; pass < 2; pass++) {
        ivec2 c = (pass == 0) ? cA : cB;
        if (pass == 1 && c == cA) break;
        if (c.x < 0 || c.y < 0 || c.x >= u_wgridDim.x || c.y >= u_wgridDim.y) continue;
        for (int k = 0; k < WGRID_K; k++) {
            float idf = texelFetch(u_wgrid, ivec2(c.x * WGRID_K + k, c.y), 0).r;
            if (idf < 0.0) break;
            int id = int(idf + 0.5);
            if (id == skip) continue;
            vec3 oc = p - texelFetch(u_occ, ivec2(id, 0), 0).xyz;
            float rmax = texelFetch(u_occ, ivec2(id, 3), 0).w;
            float b = dot(oc, d);
            if ((b > 0.0 && dot(oc, oc) > rmax * rmax) || dot(oc, oc) - b * b > rmax * rmax) continue;
            vec3 nn;
            float t = ell_hit(load_occ(id), p, d, nn);
            if (t > 0.0 && t < maxd) ao = min(ao, mix(0.08, 1.0, t / maxd));
        }
    }
    return ao;
}

// Light bounced up from the sunlit sand onto surfaces that face it (radiosity-lite).
vec3 bounce_light(vec3 N, vec3 p) {
    float fh = floor_h(p.xz);
    float h = max(p.y - fh, 0.0);
    float f = exp(-h * 0.65) * (0.5 - 0.5 * N.y);
    vec3 sandP = vec3(p.x, fh, p.z);
    float flux = (u_rt > 0.5) ? mix(0.7, 1.0, clamp(rt_flux(sandP, 2.0) * 0.5, 0.0, 1.5)) : 1.0;
    return vec3(0.80, 0.72, 0.52) * u_sunCol * sun_atten(sandP) * 0.30 * f * flux * (1.0 - 0.7 * u_gi);
}
"""

COMMON = COMMON + RT_COMMON

# Irradiance probe grid: an "ambient cube" (6 axis directions) per probe, refreshed every
# frame with two traced rays per direction and blended over time. Surfaces read it back
# with trilinear interpolation. Only the DIFFERENCE to what open water would give is applied,
# so open water looks as before while the lee of rocks darkens and coral/sand tint nearby fish.
GI_COMMON = """
uniform sampler2D u_giTex;          // atlas: x = dir * NX + ix, y = iz * NY + iy (RGBA16F)
uniform vec3 u_giOrigin;
uniform vec3 u_giStep;
uniform ivec3 u_giDim;

vec3 gi_fetch(int d, ivec3 i) {
    return texelFetch(u_giTex, ivec2(d * u_giDim.x + i.x, i.z * u_giDim.y + i.y), 0).rgb;
}

vec3 gi_cube(vec3 p, vec3 N) {
    vec3 g = clamp((p - u_giOrigin) / u_giStep, vec3(0.0), vec3(u_giDim - 1));
    ivec3 i0 = ivec3(floor(g));
    vec3 f = g - vec3(i0);
    ivec3 i1 = min(i0 + 1, u_giDim - 1);
    vec3 w = N * N;
    int dx = N.x >= 0.0 ? 0 : 1;
    int dy = N.y >= 0.0 ? 2 : 3;
    int dz = N.z >= 0.0 ? 4 : 5;
    vec3 acc = vec3(0.0);
    for (int c = 0; c < 8; c++) {
        bool bx = (c & 1) != 0, by = (c & 2) != 0, bz = (c & 4) != 0;
        ivec3 i = ivec3(bx ? i1.x : i0.x, by ? i1.y : i0.y, bz ? i1.z : i0.z);
        float t = (bx ? f.x : 1.0 - f.x) * (by ? f.y : 1.0 - f.y) * (bz ? f.z : 1.0 - f.z);
        acc += t * (w.x * gi_fetch(dx, i) + w.y * gi_fetch(dy, i) + w.z * gi_fetch(dz, i));
    }
    return acc;
}

// Indirect light arriving at p for a surface facing N.
vec3 irr(vec3 N, vec3 p) {
    if (u_gi < 0.001 || u_rt < 0.5) return ambient(N);
    vec3 w = N * N;
    // what the probes hold in open water: cosine-weighted mean of ambient() over each face's hemisphere
    vec3 base = (w.x + w.z) * amb_t(0.5) + w.y * amb_t(0.5 + (N.y >= 0.0 ? 1.0 : -1.0) / 3.0);
    return max(ambient(N) + (gi_cube(p, N) - base) * u_gi, vec3(0.0));
}
"""

COMMON = COMMON + GI_COMMON

# Screen-space refraction: transparent objects sample a copy of the opaque
# scene through an offset, with a little chromatic dispersion.
REFR_COMMON = """
uniform sampler2D u_refrTex;

vec3 refracted_bg(vec2 uv, vec2 off, float disp) {
    vec2 lo = vec2(0.002), hi = vec2(0.998);
    return vec3(texture(u_refrTex, clamp(uv + off * (1.0 - disp), lo, hi)).r,
                texture(u_refrTex, clamp(uv + off, lo, hi)).g,
                texture(u_refrTex, clamp(uv + off * (1.0 + disp), lo, hi)).b);
}
"""
COMMON = COMMON + REFR_COMMON

# Value noise, fbm and a gradient-based bump mapper for procedural materials.
NOISE_COMMON = """
float vhash(vec3 p) {
    p = fract(p * 0.3183099 + 0.1);
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}
float vnoise3(vec3 x) {
    vec3 i = floor(x);
    vec3 f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(mix(vhash(i + vec3(0, 0, 0)), vhash(i + vec3(1, 0, 0)), f.x),
                   mix(vhash(i + vec3(0, 1, 0)), vhash(i + vec3(1, 1, 0)), f.x), f.y),
               mix(mix(vhash(i + vec3(0, 0, 1)), vhash(i + vec3(1, 0, 1)), f.x),
                   mix(vhash(i + vec3(0, 1, 1)), vhash(i + vec3(1, 1, 1)), f.x), f.y), f.z);
}
float fbm3(vec3 p) { return 0.5 * vnoise3(p) + 0.25 * vnoise3(p * 2.03) + 0.125 * vnoise3(p * 4.1); }
float fbm2(vec3 p) { return 0.65 * vnoise3(p) + 0.35 * vnoise3(p * 2.1); }

// Perturb N with the gradient of fbm noise sampled at p (4-tap tetrahedron).
vec3 bump_normal(vec3 N, vec3 p, float amt) {
    const vec2 k = vec2(1.0, -1.0);
    const float e = 0.012;
    vec3 g = k.xyy * fbm2(p + k.xyy * e) + k.yyx * fbm2(p + k.yyx * e)
           + k.yxy * fbm2(p + k.yxy * e) + k.xxx * fbm2(p + k.xxx * e);
    g /= 4.0 * e;
    return normalize(N - amt * (g - N * dot(N, g)));
}
"""
COMMON = COMMON + NOISE_COMMON

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
    c += u_sunCol * 0.06 * pow(clamp(uv.y, 0.0, 1.0), 4.0);   // haze near the surface
    if (u_rt > 0.5) {                                         // ray-traced water + mirror
        vec2 px = 1.0 / vec2(textureSize(u_mirror, 0));         // soften hit edges a little
        c = (2.0 * texture(u_mirror, uv).rgb
           + texture(u_mirror, uv + vec2(px.x, 0.0)).rgb + texture(u_mirror, uv - vec2(px.x, 0.0)).rgb
           + texture(u_mirror, uv + vec2(0.0, px.y)).rgb + texture(u_mirror, uv - vec2(0.0, px.y)).rgb) / 6.0;
    }
    o_col = vec4(c, 0.0);                                     // alpha = distance (0 = far)
}
"""

# ------------------------------------------------------------------ seabed
FLOOR_VS = """
#version 330
uniform mat4 u_view;
uniform mat4 u_proj;
uniform float u_time;
in vec3 in_pos;
in vec3 in_nrm;
in vec3 in_col;
in float in_mat;
in vec2 in_uv;
out vec3 v_world;
out vec3 v_nrm;
out vec3 v_col;
out vec2 v_uv;
flat out float v_mat;
void main() {
    vec3 p = in_pos;
    if (in_mat > 5.5) {                                // sea fans sway with the current
        float sw = sin(u_time * 0.7 + in_pos.x * 1.3 + in_pos.z * 0.9) * 0.07 * in_uv.y * in_uv.y;
        p.x += sw;
        p.z += sw * 0.6;
    }
    v_world = p;
    v_nrm = in_nrm;
    v_col = in_col;
    v_uv = in_uv;
    v_mat = in_mat;
    gl_Position = u_proj * u_view * vec4(p, 1.0);
}
"""

FLOOR_FS = "#version 330\n" + COMMON + """
in vec3 v_world;
in vec3 v_nrm;
in vec3 v_col;
in vec2 v_uv;
flat in float v_mat;
out vec4 o_col;
void main() {
    int mat = int(v_mat + 0.5);
    vec3 N = normalize(v_nrm);
    if (mat == 6) {                                    // sea fan: a lattice cut out of a plane
        if (!gl_FrontFacing) N = -N;
        float u = v_uv.x, v = v_uv.y;
        float edge = 0.5 * (0.25 + 0.75 * v);
        float l1 = abs(fract(u * 9.0 + v * 6.0) - 0.5);
        float l2 = abs(fract(u * 9.0 - v * 6.0) - 0.5);
        float rib = abs(u - 0.5) < 0.012 ? 0.0 : 1.0;
        if (min(min(l1, l2), 0.5 * rib) > 0.13) discard;
    }
    vec3 albedo = v_col;
    float dist = length(u_camPos - v_world);
    float near = exp(-dist * 0.10);                    // fade fine detail with distance (no shimmer)
    float gloss = 0.0;
    if (mat == 0) {                                    // sand: grain and wind ripples
        albedo *= 0.86 + 0.26 * fbm2(v_world * vec3(5.0, 1.0, 5.0));
        if (near > 0.12) N = bump_normal(N, v_world * 16.0, 0.28 * near);
    } else if (mat == 1) {                             // rock: strata, cracks, moss on top
        float n = fbm3(v_world * 2.4);
        float strata = 0.5 + 0.5 * sin(v_world.y * 16.0 + n * 5.0);
        albedo *= (0.62 + 0.55 * n) * (0.9 + 0.2 * strata);
        albedo = mix(albedo, albedo * vec3(1.18, 1.0, 0.82), smoothstep(0.55, 0.95, strata) * 0.45);   // warm mineral bands
        float crack = smoothstep(0.022, 0.0, abs(fbm3(v_world * 3.1 + 11.0) - 0.5)) * near;
        albedo *= 1.0 - 0.38 * crack;
        vec3 bq = v_world * 46.0;
        float barn = step(0.975, vhash(floor(bq))) * smoothstep(0.42, 0.22, length(fract(bq) - 0.5))
                   * smoothstep(0.1, 0.4, N.y + 0.3) * near;
        albedo = mix(albedo, vec3(0.74, 0.72, 0.64), barn * 0.65);                                  // barnacles
        gloss = 0.14;                                                                               // wet rock
        float moss = smoothstep(0.55, 0.9, N.y) * smoothstep(0.45, 0.7, fbm3(v_world * 5.0 + 3.0));
        albedo = mix(albedo, vec3(0.16, 0.32, 0.10), moss * 0.7);
        if (near > 0.10) N = bump_normal(N, v_world * 5.0, 0.7 * near);
    } else if (mat == 3) {                             // pebbles: smooth and a little glossy
        albedo *= 0.9 + 0.2 * vnoise3(v_world * 60.0);
        gloss = 0.25;
    } else if (mat == 2) {                             // brain coral: meandering grooves
        vec3 q = v_world * 9.0;
        vec3 wq = q + 1.4 * vec3(vnoise3(q * 0.9), vnoise3(q * 0.9 + 5.0), vnoise3(q * 0.9 + 9.0));
        float ridge = 0.5 + 0.5 * sin(vnoise3(wq * 1.3) * 15.0);
        float groove = smoothstep(0.45, 0.98, ridge);
        albedo *= mix(1.10, 0.62, groove);
        albedo = mix(albedo, albedo * vec3(1.15, 1.05, 0.85) + 0.05, (1.0 - groove) * 0.25);
        if (near > 0.12) N = bump_normal(N, v_world * 22.0, 0.55 * near);
        gloss = 0.16;
    } else if (mat == 4) {                             // staghorn: polyp mounds, growth rings
        vec3 q = v_world * 62.0;
        vec3 f = fract(q) - 0.5;
        float h = vhash(floor(q));
        float polyp = smoothstep(0.34, 0.16, length(f)) * step(0.35, h);
        float pore = smoothstep(0.10, 0.04, length(f)) * step(0.35, h);
        albedo *= (0.80 + 0.35 * polyp) * (1.0 - 0.45 * pore);
        albedo *= 0.92 + 0.12 * sin(v_world.y * 70.0 + vnoise3(v_world * 8.0) * 4.0);
        if (near > 0.12) N = bump_normal(N, v_world * 40.0, 0.45 * near);
        gloss = 0.10;
    } else if (mat != 6) {                             // corals: polyps
        albedo *= 0.78 + 0.45 * smoothstep(0.35, 0.65, vnoise3(v_world * 34.0));
        if (near > 0.12) N = bump_normal(N, v_world * 24.0, 0.5 * near);
        gloss = 0.12;
    }

    vec3 L = normalize(u_sunDir);
    vec3 V = normalize(u_camPos - v_world);
    float sh = rt_shadow(v_world + N * 0.03, L, -1);
    float att = sun_atten(v_world);
    float diff = max(dot(N, L), 0.0);
    float c = (u_rt > 0.5) ? rt_flux(v_world, 1.4) * 0.5
                           : caustics(v_world.xz * 0.16, u_time * 0.55);
    float shallow = smoothstep(-6.0, 0.0, v_world.z);   // brighter nearer the glass
    float ao = (dist < 14.0) ? rt_ao(v_world + N * 0.03, N, -1) : 1.0;
    vec3 bnc = (mat != 0) ? bounce_light(N, v_world) : vec3(0.0);
    vec3 col = albedo * ((irr(N, v_world) + bnc) * ao + u_sunCol * diff * 0.75 * sh * att)
             + albedo * u_sunCol * c * sh * att * (0.55 + 0.9 * shallow);
    if (mat == 6) col += albedo * u_sunCol * att * sh * pow(max(-dot(N, L), 0.0), 1.5) * 0.5;   // light through the fan
    col += gloss * pow(max(dot(N, normalize(L + V + vec3(1e-5))), 0.0), 60.0) * u_sunCol * sh * att;
    o_col = vec4(apply_fog(col, v_world, gl_FragCoord.xy / u_res), dist);
}
"""

# -------------------------------------------------------------------- fish
FISH_ATTRS = """
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
"""

# Pose of one vertex for a given swim state. Shared by the colour pass and the
# velocity pass (which evaluates it a second time with last frame's state).
FISH_POSE = """
vec3 fishPose(vec3 ipos, vec3 ifwd, float phase, float bend, out vec3 X, out vec3 Y, out vec3 Z) {
    int part = int(in_part + 0.5);
    vec3 p = in_pos;

    float fs = 1.0;
    if (part == 1) fs = i_fin.x;
    else if (part == 2 || part == 4) fs = i_fin.y;
    else if (part == 3) fs = i_fin.z;
    p = in_pivot + (p - in_pivot) * fs;

    if (part == 3) {                       // pectoral fins flap around the body axis
        float side = sign(in_pivot.z);
        float a = sin(phase * 0.8 + side) * 0.45 * side;
        vec3 d = p - in_pivot;
        float c = cos(a), s = sin(a);
        p = in_pivot + vec3(d.x, d.y * c - d.z * s, d.y * s + d.z * c);
    }

    // A wave travels from head to tail; the tail end swings the most.
    float s = clamp(0.5 - p.x, 0.0, 1.6);
    float w = s * s * (0.35 + 0.65 * s);
    float wave = sin(phase - s * 5.5);
    float len = i_size.x;
    vec3 local = p * vec3(1.0, i_size.y, i_size.z) * len;
    local.z += (i_fin.w * wave * w * 0.20 + bend * s * s * 0.45) * len;

    X = normalize(ifwd);
    Z = cross(X, vec3(0.0, 1.0, 0.0));
    Z = normalize(Z + vec3(1e-4, 0.0, 0.0));
    Y = cross(Z, X);
    return ipos + X * local.x + Y * local.y + Z * local.z;
}
"""

FISH_VS = """
#version 330
uniform mat4 u_view;
uniform mat4 u_proj;
""" + FISH_ATTRS + """
out vec3 v_world;
out vec3 v_nrm;
out vec2 v_uv;
out vec3 v_local;
out vec3 v_nloc;
flat out float v_part;
flat out float v_pattern;
flat out float v_sy;
flat out int v_id;
flat out vec3 v_fwd;
flat out vec3 v_c1;
flat out vec3 v_c2;
flat out vec3 v_c3;

""" + FISH_POSE + """
void main() {
    vec3 X, Y, Z;
    vec3 world = fishPose(i_pos, i_fwd, i_anim.x, i_anim.y, X, Y, Z);

    vec3 nl = normalize(in_nrm / vec3(1.0, i_size.y, i_size.z));
    v_nrm = X * nl.x + Y * nl.y + Z * nl.z;
    v_world = world;
    v_uv = in_uv;
    v_local = in_pos;
    v_nloc = in_nrm;
    v_part = in_part;
    v_pattern = i_anim.z;
    v_sy = i_size.y;
    v_id = gl_InstanceID;
    v_fwd = X;
    v_c1 = i_c1;
    v_c2 = i_c2;
    v_c3 = i_c3;
    gl_Position = u_proj * u_view * vec4(world, 1.0);
}
"""



# One texel of the probe atlas per fragment: trace two cosine-weighted rays for one axis
# direction of one probe and blend into the history (read from u_giTex).
GI_UPDATE_FS = "#version 330\n" + COMMON + """
uniform float u_first;
out vec4 o_col;

vec3 gi_axis(int d) {
    if (d == 0) return vec3(1.0, 0.0, 0.0);
    if (d == 1) return vec3(-1.0, 0.0, 0.0);
    if (d == 2) return vec3(0.0, 1.0, 0.0);
    if (d == 3) return vec3(0.0, -1.0, 0.0);
    if (d == 4) return vec3(0.0, 0.0, 1.0);
    return vec3(0.0, 0.0, -1.0);
}

// Radiance arriving along -d at p: occluder, sea floor or open water.
vec3 gi_trace(vec3 p, vec3 d) {
    const float maxd = 7.0;
    float te = 1e9;
    int hid = -1;
    vec3 hn = vec3(0.0, 1.0, 0.0);
    ivec2 prev = ivec2(-1000);
    for (int s = 0; s < 4; s++) {                       // the ray crosses up to four 2 m cells
        vec3 q = p + d * (maxd * float(s) / 3.0);
        ivec2 c = ivec2(floor((q.xz - u_wgridOrigin) / u_wcell));
        if (c == prev) continue;
        prev = c;
        if (c.x < 0 || c.y < 0 || c.x >= u_wgridDim.x || c.y >= u_wgridDim.y) continue;
        for (int k = 0; k < WGRID_K; k++) {
            float idf = texelFetch(u_wgrid, ivec2(c.x * WGRID_K + k, c.y), 0).r;
            if (idf < 0.0) break;
            int id = int(idf + 0.5);
            vec3 oc = p - texelFetch(u_occ, ivec2(id, 0), 0).xyz;
            float rmax = texelFetch(u_occ, ivec2(id, 3), 0).w;
            float b = dot(oc, d);
            if ((b > 0.0 && dot(oc, oc) > rmax * rmax) || dot(oc, oc) - b * b > rmax * rmax) continue;
            Occ o = load_occ(id);
            if (o.opac < 0.5) continue;
            vec3 nn;
            float t = ell_hit(o, p, d, nn);
            if (t > 0.0 && t < te && t < maxd) { te = t; hid = id; hn = nn; }
        }
    }
    float tf = -1.0;
    if (d.y < -0.001) {
        float tt = (u_floor - p.y) / d.y;
        for (int i = 0; i < 4; i++) {
            vec3 q = p + d * tt;
            tt += (floor_h(q.xz) - q.y) / d.y;
        }
        if (tt > 0.0 && tt < maxd) tf = tt;
    }
    vec3 L = normalize(u_sunDir);
    if (hid >= 0 && (tf < 0.0 || te < tf)) {
        vec3 hp = p + d * te;
        float sh = rt_shadow(hp + hn * 0.05, L, hid);
        vec3 rad = load_occ(hid).col * (ambient(hn) * 0.8 + u_sunCol * max(dot(hn, L), 0.0) * sh * sun_atten(hp) * 0.55);
        return rad / (1.0 + te * te * 0.03);
    }
    if (tf > 0.0) {
        vec3 hp = p + d * tf;
        float flux = rt_flux(hp, 2.0) * 0.5;
        vec3 rad = vec3(0.80, 0.72, 0.52) * (ambient(vec3(0.0, 1.0, 0.0)) * 0.8
            + u_sunCol * sun_atten(hp) * max(L.y, 0.0) * (0.5 + 0.5 * flux) * 0.6);
        return rad / (1.0 + tf * tf * 0.03);
    }
    return ambient(d);                                  // open water
}

void main() {
    ivec2 px = ivec2(gl_FragCoord.xy);
    int dir = px.x / u_giDim.x;
    int ix = px.x - dir * u_giDim.x;
    int iz = px.y / u_giDim.y;
    int iy = px.y - iz * u_giDim.y;
    vec3 p = u_giOrigin + vec3(float(ix), float(iy), float(iz)) * u_giStep;
    p.y = max(p.y, floor_h(p.xz) + 0.08);               // probes below the sand are lifted onto it
    vec3 N = gi_axis(dir);
    vec3 acc = vec3(0.0);
    for (int s = 0; s < 2; s++) {
        vec2 xi = vec2(hash12(gl_FragCoord.xy + u_frame * 7.13 + float(s) * 19.7),
                       hash12(gl_FragCoord.yx * 1.7 + u_frame * 3.91 + float(s) * 5.3));
        acc += gi_trace(p, cosine_dir(N, xi));
    }
    vec3 cur = acc * 0.5;
    if (any(isnan(cur)) || any(isinf(cur))) cur = ambient(N);
    vec3 hist = texelFetch(u_giTex, px, 0).rgb;
    if (any(isnan(hist)) || any(isinf(hist))) hist = cur;
    float a = (u_first > 0.5) ? 1.0 : 0.07;
    o_col = vec4(mix(hist, cur, a), 1.0);
}
"""

# ---------------------------------------------------------- velocity (motion) pass
# Writes, per pixel of a moving object, where that surface point was on screen last
# frame (xy = previous uv, w = 1). Everything else is left at 0 and falls back to the
# camera-only reprojection in the TAA pass.
FISH_VEL_VS = """
#version 330
uniform mat4 u_view;
uniform mat4 u_proj;
uniform mat4 u_prevVP;
in vec3 in_pos;
in float in_part;
in vec3 in_pivot;
in vec3 i_pos;
in vec3 i_fwd;
in vec4 i_size;
in vec4 i_fin;
in vec4 i_anim;
in vec3 p_pos;
in vec3 p_fwd;
in vec2 p_anim;
out vec4 v_prev;
""" + FISH_POSE + """
void main() {
    vec3 X, Y, Z;
    vec3 world = fishPose(i_pos, i_fwd, i_anim.x, i_anim.y, X, Y, Z);
    vec3 prevWorld = fishPose(p_pos, p_fwd, p_anim.x, p_anim.y, X, Y, Z);
    v_prev = u_prevVP * vec4(prevWorld, 1.0);
    gl_Position = u_proj * u_view * vec4(world, 1.0);
}
"""

FISH_VEL_FS = """
#version 330
in vec4 v_prev;
out vec4 o_col;
void main() {
    vec2 puv = v_prev.xy / max(v_prev.w, 1e-4) * 0.5 + 0.5;
    o_col = vec4(puv, 0.0, 1.0);
}
"""

# Occluders in the velocity pass: depth only, no motion of their own.
VEL_CLEAR_FS = """
#version 330
out vec4 o_col;
void main() { o_col = vec4(0.0); }
"""

# Body and fins share the same helper functions; fins are drawn in a second,
# alpha-blended pass because they are thin translucent membranes.
FISH_FUNCS = """
in vec3 v_world;
in vec3 v_nrm;
in vec2 v_uv;
in vec3 v_local;
in vec3 v_nloc;
flat in float v_part;
flat in float v_pattern;
flat in float v_sy;
flat in int v_id;
flat in vec3 v_fwd;
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
    } else if (pat == 6) {                            // lionfish: fine vertical stripes
        float st = smoothstep(0.35, 0.65, 0.5 + 0.5 * sin(t * 62.0));
        col = mix(v_c1, v_c2, st);
        col *= 0.85 + 0.25 * smoothstep(-0.3, 0.5, v);
    } else if (pat == 7) {                            // discus: wavy horizontal stripes
        float w = 0.5 + 0.5 * sin(v * 13.0 + sin(t * 9.0) * 2.2);
        col = mix(v_c1, v_c3, smoothstep(0.62, 0.80, w) * 0.85);
        col = mix(v_c2 * 0.9, col, smoothstep(-0.7, 0.2, v));
    } else {                                          // tuna: lateral yellow line
        col = mix(v_c2, v_c1, smoothstep(-0.30, 0.40, v));
        col = mix(col, v_c3, smoothstep(0.10, 0.0, abs(v - 0.05)) * 0.5 * step(0.2, t));
    }
    return col;
}

vec3 fin_color(int pat, float along, float outv) {
    vec3 c = mix(v_c1, v_c2, 0.4);
    if (pat == 0) c = vec3(0.75, 0.82, 0.92) * 0.75;
    else if (pat == 1) c = mix(v_c1, v_c3, smoothstep(0.80, 1.0, outv));
    else if (pat == 2) c = (v_part < 1.5) ? vec3(1.0, 0.82, 0.10) : mix(v_c1, v_c3, smoothstep(0.7, 1.0, outv));
    else if (pat == 3) c = v_c1 * 0.8;
    else if (pat == 4) c = mix(v_c1 * 0.9, v_c3, smoothstep(0.55, 1.0, outv));
    else if (pat == 6) c = mix(v_c1, v_c2, step(0.5, fract(along * 14.0)));
    else if (pat == 7) c = mix(v_c1, v_c3, smoothstep(0.4, 1.0, outv));
    else c = (v_part < 2.5) ? v_c1 : vec3(0.95, 0.8, 0.1);
    return c;
}
"""

FISH_FS = "#version 330\n" + COMMON + FISH_FUNCS + """
void main() {
    vec3 N = normalize(v_nrm);
    int pat = int(v_pattern + 0.5);
    float t = v_uv.x;
    float v = v_uv.y;
    float emis = 0.0;
    vec2 warp = vec2(vnoise3(vec3(t * 22.0, v * 6.0, float(v_id))),
                     vnoise3(vec3(t * 22.0 + 7.0, v * 6.0, float(v_id) + 3.0))) - 0.5;
    vec3 albedo = body_color(pat, t + 0.014 * warp.x, v + 0.10 * warp.y, emis);
    albedo *= 0.93 + 0.14 * vnoise3(vec3(t * 9.0, v * 3.0, float(v_id) * 1.7));      // mottled skin

    // gills and mouth
    float gill = smoothstep(0.012, 0.0, abs(t - 0.215 - 0.045 * v * v)) * step(-0.65, v) * step(v, 0.85);
    albedo = mix(albedo * (1.0 - 0.45 * gill), vec3(0.45, 0.08, 0.08), gill * 0.25);
    albedo *= 1.0 - 0.7 * smoothstep(0.012, 0.0, abs(v + 0.28)) * smoothstep(0.08, 0.02, t);

    // eye: iris ring + pupil on the side-facing flanks
    vec2 e = vec2(v_local.x - 0.375, (v_local.y - 0.03) * v_sy);
    float d = length(e);
    float eyeMask = (abs(v_nloc.z) > 0.35 && v_local.x > 0.30) ? smoothstep(0.034, 0.030, d) : 0.0;
    if (eyeMask > 0.0) {
        float ang = atan(e.y, e.x);
        vec3 iris = mix(vec3(0.50, 0.28, 0.06), vec3(0.98, 0.80, 0.30), 0.5 + 0.5 * sin(ang * 22.0 + d * 90.0));
        iris *= 0.75 + 0.5 * smoothstep(0.010, 0.026, d);                    // brighter toward the rim
        vec3 eyeCol = mix(vec3(0.82, 0.80, 0.74), iris, smoothstep(0.031, 0.026, d));   // pale sclera -> iris
        eyeCol = mix(eyeCol, vec3(0.03, 0.02, 0.01), smoothstep(0.030, 0.027, d) * smoothstep(0.022, 0.026, d));  // limbus
        eyeCol = mix(eyeCol, vec3(0.005), smoothstep(0.013, 0.010, d));      // pupil
        albedo = mix(albedo, eyeCol, eyeMask);
        albedo += vec3(1.0) * smoothstep(0.0085, 0.0040, length(e - vec2(0.007, 0.009))) * eyeMask;
        albedo += vec3(0.6) * smoothstep(0.0040, 0.0015, length(e - vec2(-0.008, -0.007))) * eyeMask;
        vec3 upv = normalize(vec3(0.0, 1.0, 0.0) - v_fwd * v_fwd.y);
        N = normalize(N + (v_fwd * e.x + upv * e.y) / 0.034 * 0.55 * eyeMask);     // domed lens
    }

    // scales: overlapping plates, lit toward their free rear edge. They fade out once they
    // get close to a pixel in size, so distant fish do not shimmer.
    float scaleAmt = (pat == 3) ? 0.10 : ((pat == 5 || pat == 0) ? 0.30 : 0.22);
    vec2 sg = vec2(t * 48.0, v * 10.0);
    sg.x += 0.5 * mod(floor(sg.y), 2.0);
    vec2 cell = floor(sg);
    vec2 fs = fract(sg);
    float rnd = hash12(cell + float(v_id) * 3.7);
    float vis = (1.0 - smoothstep(0.30, 0.65, max(fwidth(sg.x), fwidth(sg.y)))) * (1.0 - eyeMask);
    float plate = mix(0.78, 1.08, smoothstep(0.0, 0.8, fs.x)) * (0.90 + 0.20 * (1.0 - abs(fs.y - 0.5) * 2.0));
    albedo *= mix(1.0, plate * (0.93 + 0.14 * rnd), vis * min(1.0, scaleAmt * 3.2));
    N = normalize(N + (v_fwd * (0.5 - fs.x) + cross(N, v_fwd) * (0.5 - fs.y)) * 0.30 * scaleAmt * vis);
    float glint = (pat == 0 || pat == 4 || pat == 5) ? smoothstep(0.90, 0.99, rnd) * vis : 0.0;    // a few plates catch the light

    float gd = t - 0.215 - 0.045 * v * v;                               // gill cover: raised rim, crease behind it
    float ridge = exp(-pow(gd / 0.007, 2.0)) * step(-0.65, v) * step(v, 0.85);
    N = normalize(N - v_fwd * clamp(gd / 0.010, -1.0, 1.0) * ridge * 0.45);
    albedo *= 1.0 - 0.30 * ridge * smoothstep(0.0, -0.012, gd);

    float lat = smoothstep(0.030, 0.0, abs(v + 0.02 - 0.03 * sin(t * 9.0))) * step(0.22, t) * step(t, 0.92);
    albedo *= 1.0 - 0.30 * lat * (0.35 + 0.65 * smoothstep(0.30, 0.55, 0.5 + 0.5 * sin(t * 48.0 * 6.2832))) * vis;

    vec3 L = normalize(u_sunDir);
    vec3 V = normalize(u_camPos - v_world);
    float ndl = dot(N, L);
    float diff = max(ndl, 0.0);
    float wrap = max((ndl + 0.6) / 1.6, 0.0);
    float sh = rt_shadow(v_world + N * 0.01, L, u_nstatic + v_id);
    float att = sun_atten(v_world);
    float ndv = max(dot(N, V), 0.0);
    float ao = rt_ao(v_world + N * 0.02, N, u_nstatic + v_id);
    vec3 lit = (irr(N, v_world) + bounce_light(N, v_world)) * ao + u_sunCol * att * sh * (0.55 * diff + 0.35 * wrap);
    vec3 col = albedo * lit;
    float cz = (u_rt > 0.5) ? rt_flux(v_world, 1.4) * 0.5
                            : caustics(v_world.xz * 0.16 + v_world.y * 0.05, u_time * 0.55);
    col += albedo * u_sunCol * att * sh * cz * 0.35 * max(N.y, 0.0);

    // subsurface scattering: backlit thin edges glow with the light passing through
    float back = pow(max(dot(V, -L), 0.0), 2.0);
    col += albedo * u_sunCol * att * sh * back * pow(clamp(1.0 - ndv, 0.0, 1.0), 1.5) * 0.8;
    // thin-film iridescence on shiny species
    if (pat == 0 || pat == 4 || pat == 5) {
        vec3 irid = 0.5 + 0.5 * cos(6.2831853 * (ndv * 1.2 + u_time * 0.05 + vec3(0.0, 0.33, 0.67)));
        col += albedo * irid * 0.40 * u_irid * (0.25 + 0.75 * clamp(1.0 - ndv, 0.0, 1.0)) * (0.3 + 0.7 * att * sh);
    }

    vec3 H = normalize(L + V + vec3(1e-5));
    float spec = pow(max(dot(N, H), 0.0), 70.0) * 0.55 * sh;
    spec += eyeMask * pow(max(dot(N, H), 0.0), 300.0) * 3.0 * sh;      // wet, glossy eye
    spec += glint * pow(max(dot(N, H), 0.0), 40.0) * 0.40 * sh;
    col += spec * u_sunCol;
    // environment reflection: wet skin mirrors the bright water above and what the probes see around it
    vec3 R = reflect(-V, N);
    float fres = pow(clamp(1.0 - ndv, 0.0, 1.0), 4.0);
    float gloss = (pat == 3) ? 0.35 : ((pat == 0 || pat == 4 || pat == 5) ? 1.0 : 0.6);
    gloss = mix(gloss, 1.4, eyeMask);                                   // the eye is the wettest part
    vec3 env = irr(R, v_world + N * 0.05);
    env += vec3(0.45, 0.70, 0.85) * smoothstep(-0.1, 0.7, R.y) * (0.15 + 0.85 * u_day) * att * 1.2;
    col += (0.12 + 0.90 * fres) * gloss * (0.4 + 0.6 * ao) * env;
    float rim = pow(clamp(1.0 - ndv, 0.0, 1.0), 3.0);
    col += rim * vec3(0.10, 0.26, 0.36) * (0.4 + 0.6 * u_day);
    col += albedo * emis * 0.9;                       // neon stripes glow (feeds the bloom)

    o_col = vec4(apply_fog(col, v_world, gl_FragCoord.xy / u_res), length(u_camPos - v_world));
}
"""

# Fins: translucent membranes, thicker near the body, lit from both sides, with
# extra glow when the sun shines through them.
FIN_FS = "#version 330\n" + COMMON + FISH_FUNCS + """
void main() {
    vec3 N = normalize(v_nrm);
    if (!gl_FrontFacing) N = -N;
    int part = int(v_part + 0.5);
    int pat = int(v_pattern + 0.5);
    vec3 albedo = fin_color(pat, v_uv.x, v_uv.y);

    float along = v_uv.x, outv = v_uv.y;
    float rr = along * ((part == 1) ? 22.0 : 26.0);
    float dr1 = abs(fract(rr) - 0.5) * 2.0;                            // 0 on a ray, 1 in the gap
    float dr2 = abs(fract(rr * 2.0) - 0.5) * 2.0;                      // rays fork toward the tip
    float dray = mix(dr1, dr2, smoothstep(0.35, 0.75, outv));
    float rayLine = smoothstep(0.50, 0.12, dray);
    rayLine = mix(rayLine, 0.45, smoothstep(0.35, 0.80, fwidth(rr)));  // no moire when the rays get dense
    float base = smoothstep(0.30, 0.0, outv);
    float alpha = mix(0.24, 0.86, rayLine);
    alpha = max(alpha * mix(1.0, 0.7, smoothstep(0.5, 1.0, outv)), base * 0.92);
    float cut = 0.95 - 0.07 * dray;                                    // membrane recedes between the rays
    alpha *= 1.0 - smoothstep(cut - 0.03, cut + 0.03, outv);
    albedo *= mix(1.04, 0.80, rayLine);

    vec3 L = normalize(u_sunDir);
    float sh = rt_shadow(v_world, L, u_nstatic + v_id);
    float att = sun_atten(v_world);
    float ndl = dot(N, L);
    float through = pow(max(-ndl, 0.0), 1.4);          // sun shining through the membrane
    vec3 lit = irr(N, v_world) + bounce_light(N, v_world) * 0.5 + u_sunCol * att * sh * (0.40 * abs(ndl) + 0.75 * through);
    vec3 col = albedo * lit;
    vec3 Vf = normalize(u_camPos - v_world);                // membrane edges scatter the surroundings
    col += albedo * irr(reflect(-Vf, N), v_world) * 0.25 * pow(clamp(1.0 - abs(dot(N, Vf)), 0.0, 1.0), 3.0);
    float cz = (u_rt > 0.5) ? rt_flux(v_world, 1.4) * 0.5
                            : caustics(v_world.xz * 0.16 + v_world.y * 0.05, u_time * 0.55);
    col += albedo * u_sunCol * att * sh * cz * 0.25;
    col = apply_fog(col, v_world, gl_FragCoord.xy / u_res);
    o_col = vec4(col * alpha, alpha);                   // premultiplied
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
in float i_kind;
out vec3 v_world;
out vec3 v_nrm;
out vec3 v_col;
out float v_u;
out float v_side;
out vec3 v_lat;
flat out float v_kind;
void main() {
    float u = in_uv.x;
    float side = in_uv.y;
    float h = i_dim.x;
    bool anem = i_kind > 0.5 && i_kind < 1.5;
    float sway = (sin(u_time * 0.9 + i_dim.z + u * 2.8) * 0.22
               + sin(u_time * 0.45 + i_dim.z * 1.7 + u * 1.3) * 0.12) * (anem ? 1.6 : 1.0);
    vec3 lat = vec3(cos(i_dim.w), 0.0, sin(i_dim.w));
    vec3 across = vec3(-lat.z, 0.0, lat.x);
    float amp = u * u * h * (anem ? 0.80 : 0.45);
    float width = anem ? i_dim.y * (1.0 - 0.75 * u)
                       : i_dim.y * (1.0 - 0.65 * u) * (0.85 + 0.25 * sin(u * 9.0 + i_dim.z));
    float current = sin(u_time * 0.25 + i_base.x * 0.08) * 0.12 * u * u * h;      // slow shared surge
    vec3 world = i_base + vec3(0.0, u * h - sway * sway * amp * 0.15, 0.0)
               + across * (sway * amp + current) + lat * side * width;
    v_world = world;
    v_nrm = across;
    v_lat = lat;
    v_col = i_col;
    v_u = u;
    v_side = side;
    v_kind = i_kind;
    gl_Position = u_proj * u_view * vec4(world, 1.0);
}
"""

KELP_FS = "#version 330\n" + COMMON + """
in vec3 v_world;
in vec3 v_nrm;
in vec3 v_col;
in float v_u;
in float v_side;
in vec3 v_lat;
flat in float v_kind;
out vec4 o_col;
void main() {
    vec3 N = normalize(v_nrm);
    if (!gl_FrontFacing) N = -N;
    bool anem = v_kind > 0.5 && v_kind < 1.5;
    bool grass = v_kind > 1.5;
    // blades curl slightly across their width, anemone tentacles are round tubes
    N = normalize(N + v_lat * v_side * (anem ? 1.1 : 0.45));
    vec3 L = normalize(u_sunDir);
    vec3 V = normalize(u_camPos - v_world);

    float aa = 1.0 - smoothstep(0.5, 1.2, fwidth(v_side) * 14.0);          // veins fade before they alias
    float rib = smoothstep(0.12, 0.0, abs(v_side));
    float veins = 0.5 + 0.5 * sin(v_side * 22.0 + vnoise3(v_world * 6.0) * 2.0);
    float blotch = vnoise3(v_world * vec3(7.0, 2.5, 7.0));
    float leaf = anem ? 0.0 : 1.0;
    vec3 albedo = v_col * mix(0.55, 1.25, v_u);                            // darker toward the holdfast
    albedo = mix(albedo, albedo * vec3(1.18, 1.10, 0.62), smoothstep(0.55, 1.0, v_u) * 0.5);   // sun-bleached tips
    albedo *= 0.82 + 0.36 * blotch;
    albedo *= 1.0 - 0.14 * veins * aa * leaf;
    albedo = mix(albedo, albedo * vec3(1.15, 1.20, 0.80), rib * aa * 0.5 * leaf);                // pale midrib
    albedo *= 0.90 + 0.10 * smoothstep(0.0, 0.25, abs(v_side));
    float fleck = step(0.965, vnoise3(v_world * vec3(40.0, 14.0, 40.0)));
    albedo = mix(albedo, vec3(0.85, 0.82, 0.70), fleck * 0.5 * (1.0 - v_u) * ((grass || anem) ? 0.0 : 1.0));   // epiphytes
    if (anem) albedo *= 0.90 + 0.10 * sin(v_u * 60.0);                     // faint rings along the tentacle

    float trans = pow(max(dot(-N, L), 0.0), 1.5) * (0.35 + 0.35 * abs(v_side) + 0.30 * (1.0 - rib));
    float sh = rt_shadow(v_world, L, -1);
    float att = sun_atten(v_world);
    float ao = rt_ao(v_world, N, -1);
    vec3 lit = (irr(N, v_world) + bounce_light(N, v_world)) * ao + u_sunCol * att * sh * (0.45 * abs(dot(N, L)) + trans);
    vec3 col = albedo * lit;
    float cz = (u_rt > 0.5) ? rt_flux(v_world, 1.4) * 0.5
                            : caustics(v_world.xz * 0.16 + v_world.y * 0.1, u_time * 0.55);
    col += albedo * u_sunCol * att * sh * cz * 0.25;
    col += u_sunCol * sh * att * pow(max(dot(N, normalize(L + V)), 0.0), 40.0) * 0.22;    // wet sheen
    if (anem) {                                                             // glowing, pale-tipped tentacles
        col += v_col * 0.9 * smoothstep(0.55, 1.0, v_u) * (0.45 + 0.55 * u_day);
        col = mix(col, v_col * 1.3 + 0.35, smoothstep(0.86, 1.0, v_u) * 0.5);
    }
    o_col = vec4(apply_fog(col, v_world, gl_FragCoord.xy / u_res), length(u_camPos - v_world));
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
uniform mat4 u_view;
uniform mat4 u_proj;
in vec3 v_world;
in vec3 v_nrm;
in vec3 v_col;
in vec3 v_local;
out vec4 o_col;
void main() {
    vec3 N = normalize(v_nrm);
    N = bump_normal(N, v_local * 9.0, 0.12);                              // faintly warty surface
    vec3 V = normalize(u_camPos - v_world);
    float ndv = abs(dot(N, V));
    float fres = pow(clamp(1.0 - ndv, 0.0, 1.0), 2.0);
    vec2 uv = gl_FragCoord.xy / u_res;

    // Lens: bend the view ray by the surface normal; pixels-per-world-unit
    // at this depth turns that into a screen offset. Stronger toward the rim.
    vec3 nv = mat3(u_view) * N;
    float dist = length(u_camPos - v_world);
    float ppu = u_proj[1][1] * u_res.y * 0.5 / dist;
    vec2 off = -nv.xy * ppu * 0.50 * (0.35 + 0.65 * fres) / u_res;
    vec3 seen = refracted_bg(uv, off, 0.10);

    float veins = 0.5 + 0.5 * sin(atan(v_local.z, v_local.x) * 14.0);
    vec3 glow = v_col * (0.30 + 0.55 * fres + 0.22 * veins * (1.0 - v_local.y));
    glow = apply_fog(glow * (0.55 + 0.45 * u_day), v_world, uv);
    vec3 tint = mix(vec3(1.0), v_col * 1.25, 0.40);
    vec3 col = seen * tint * 0.95 + glow * (0.30 + 0.5 * fres);
    float a = 0.50 + 0.40 * fres;

    // anatomy seen through the bell: radial canals, ring canal, gonads, muscular rim
    float ang = atan(v_local.z, v_local.x);
    float rho = length(v_local.xz);
    float hh = clamp((v_local.y + 0.14) / 0.94, 0.0, 1.0);               // 0 at the rim, 1 at the apex
    float canal = smoothstep(0.05, 0.0, abs(sin(ang * 4.0))) * smoothstep(0.05, 0.25, rho)
                + 0.45 * smoothstep(0.06, 0.0, abs(sin(ang * 8.0 + 0.39))) * smoothstep(0.35, 0.8, rho);
    canal = max(canal, smoothstep(0.045, 0.0, abs(hh - 0.07)));
    col = mix(col, v_col * 0.45, clamp(canal, 0.0, 1.0) * 0.55);
    a += clamp(canal, 0.0, 1.0) * 0.22;
    float lobe = smoothstep(0.17, 0.0, abs(rho - 0.40)) * smoothstep(0.30, 0.60, 0.5 + 0.5 * cos(ang * 4.0 + 0.78))
               * smoothstep(0.30, 0.50, hh);
    col = mix(col, vec3(1.0, 0.55, 0.68) * (0.6 + 0.4 * u_day), lobe * 0.85);
    a = max(a, 0.80 * lobe);
    float rimb = smoothstep(0.16, 0.0, hh);
    col = mix(col, v_col * 1.35, rimb * 0.55);
    a += rimb * 0.28;
    a += 0.14 * step(0.945, vhash(floor(v_local * 42.0)));                // nematocyst warts
    o_col = vec4(col * min(a, 0.97), min(a, 0.97));
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
out float v_arm;
void main() {
    float u = in_t.x;
    float k = in_t.z;
    bool arm = k > 13.5;                                  // k 0..13 thin tentacles, 14..17 oral arms
    float ang = arm ? 6.2831853 * (k - 14.0) / 4.0 + 0.4 : 6.2831853 * k / 14.0;
    float pulse = sin(i_phase);
    float rim = arm ? 0.16 : 0.85 * (1.0 - 0.14 * pulse);
    vec3 top = vec3(cos(ang) * rim, arm ? 0.02 : -0.12, sin(ang) * rim);
    float len = (arm ? 1.0 : 2.3) + (arm ? 0.35 : 0.8) * fract(sin(k * 12.9898) * 43758.5453);
    vec3 p = top + vec3(0.0, -u * len, 0.0);
    float sw = arm ? 0.20 : 0.12;
    p.x += sin(u_time * 1.4 + u * 5.0 - i_phase * 0.5 + k) * sw * u;
    p.z += cos(u_time * 1.1 + u * 4.0 + k * 1.7) * sw * u;
    float wid = arm ? 0.075 * (1.0 - 0.45 * u) * (1.0 + 0.45 * sin(u * 26.0 + k))    // frilly
                    : 0.018 * (1.0 - 0.6 * u);
    vec3 side = vec3(-sin(ang), 0.0, cos(ang)) * in_t.y * wid;
    v_arm = arm ? 1.0 : 0.0;
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
in float v_arm;
out vec4 o_col;
void main() {
    float a = mix((1.0 - v_u) * 0.55 * (0.72 + 0.28 * sin(v_u * 90.0)), (1.0 - 0.7 * v_u) * 0.75, v_arm);
    vec3 base = mix(v_col, vec3(1.0, 0.88, 0.94), 0.40 * v_arm);
    vec3 col = apply_fog(base * (0.6 + 0.4 * u_day), v_world, gl_FragCoord.xy / u_res);
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
out vec2 v_center;
out float v_psize;
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
    v_center = clip.xy / clip.w * 0.5 + 0.5;
    v_psize = gl_PointSize;
}
"""

BUBBLE_FS = "#version 330\n" + COMMON + """
in float v_alpha;
in vec3 v_world;
in vec2 v_center;
in float v_psize;
out vec4 o_col;
void main() {
    vec2 c = gl_PointCoord * 2.0 - 1.0;
    float d = length(c);
    if (d > 1.0) discard;
    float R = v_psize * 0.5;
    vec2 off_px = vec2(c.x, -c.y) * R;                 // this pixel relative to the bubble centre
    // an air bubble in water is a diverging lens: the image inside is inverted
    // and wide-angle, so look up the background mirrored about the centre
    vec2 look = v_center - off_px * 1.6 / u_res;
    vec3 bg = refracted_bg(look, -off_px * 0.25 / u_res, 0.18);
    float rim = smoothstep(0.62, 0.95, d) * (1.0 - smoothstep(0.95, 1.0, d));
    float hl = smoothstep(0.38, 0.0, length(c - vec2(-0.35, 0.40)));
    vec3 col = bg * (0.80 + 0.15 * rim) + vec3(0.75, 0.93, 1.0) * (rim * 0.55 + hl * 0.9)
             * (0.4 + 0.6 * max(u_day, 0.3));
    float a = v_alpha * smoothstep(1.0, 0.90, d);
    float f = 1.0 - exp(-length(u_camPos - v_world) * u_fog);
    o_col = vec4(col * a, a);
}
"""

SNOW_VS = """
#version 330
uniform mat4 u_view;
uniform mat4 u_proj;
uniform float u_time;
uniform float u_resy;
out float v_alpha;
out vec3 v_world;
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
    v_world = world;
}
"""

SNOW_FS = "#version 330\n" + COMMON + """
in float v_alpha;
in vec3 v_world;
out vec4 o_col;
void main() {
    vec2 c = gl_PointCoord * 2.0 - 1.0;
    float lit = 1.0;
    if (u_rt > 0.5) lit = rt_flux(v_world, 3.0) * rt_shadow(v_world, normalize(u_sunDir), -1);
    float a = smoothstep(1.0, 0.2, length(c)) * v_alpha * 0.55 * (0.30 + 1.7 * lit);   // sparkles in light shafts
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
        float z = (q - c) / w;
        sum += exp(-z * z) * flick;
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

vec3 safe3(vec3 c) { return (any(isnan(c)) || any(isinf(c))) ? vec3(0.0) : c; }
void main() {   // 4 bilinear taps = a 4x4 box average
    vec3 c = safe3(texture(u_tex, uv + u_texel * vec2(-1.0, -1.0)).rgb)
           + safe3(texture(u_tex, uv + u_texel * vec2( 1.0, -1.0)).rgb)
           + safe3(texture(u_tex, uv + u_texel * vec2(-1.0,  1.0)).rgb)
           + safe3(texture(u_tex, uv + u_texel * vec2( 1.0,  1.0)).rgb);
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
uniform float u_dither;
uniform float u_ca;
uniform float u_grain;
uniform float u_photo;
in vec2 uv;
out vec4 o_col;
float hash12(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}
void main() {
    vec2 dd = uv - 0.5;
    float ca = u_ca * 0.004;                      // lens fringing grows toward the edges
    vec3 c = vec3(texture(u_scene, uv + dd * ca).r,
                  texture(u_scene, uv).g,
                  texture(u_scene, uv - dd * ca).b)
           + texture(u_bloom1, uv).rgb * u_g1
           + texture(u_bloom2, uv).rgb * u_g2;
    vec2 d = (uv - 0.5) * vec2(u_res.x / u_res.y * 0.55, 1.0) * 2.0;
    c *= 1.0 - u_vig * smoothstep(0.55, 1.6, length(d));
    if (any(isnan(c)) || any(isinf(c))) c = vec3(0.0);
    vec3 soft = c / (1.0 + 0.12 * c);            // gentle highlight roll-off
    if (u_photo > 0.001) {
        vec3 x = c * 1.08;                        // filmic curve (Narkowicz ACES fit): contrast in the mids, soft shoulder
        vec3 film = clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
        float luma = dot(film, vec3(0.30, 0.59, 0.11));
        film = mix(vec3(luma), film, 0.86);       // real water is less saturated than a render
        film += vec3(-0.004, 0.006, 0.010) * (1.0 - luma) * (1.0 - luma);     // cool shadows
        film += vec3(0.012, 0.006, -0.008) * luma * luma;                     // warm highlights
        soft = mix(soft, film, u_photo);
    }
    c = soft;
    c += (hash12(gl_FragCoord.xy + fract(u_time) * 91.0) - 0.5) / 255.0 * u_dither;   // de-band gradients
    c += (hash12(gl_FragCoord.xy * 1.37 + fract(u_time * 7.0) * 131.0) - 0.5) * u_grain * 0.06
         * (1.0 - 0.6 * clamp(dot(c, vec3(0.3, 0.59, 0.11)), 0.0, 1.0));      // film grain
    o_col = vec4(c, 1.0);
}
"""


# ----------------------------------------------------- ray-traced passes
# Forward light tracing: every vertex of the water-surface grid refracts a sun
# ray (Snell's law) down to the floor plane; the ratio between the area the
# flat surface would cover and the area it actually covers is the focusing.
CAUSTIC_VS = "#version 330\n" + WAVES + """
uniform float u_time;
uniform vec3 u_sunDir;
uniform vec2 u_mapOrigin;
uniform vec2 u_mapSize;
in vec2 in_xz;
out float v_flux;

// Where the sun ray that crosses the surface at xz lands on the floor plane.
vec2 land(vec2 xz, vec3 I) {
    vec3 s = vec3(xz.x, surf_h(xz, u_time), xz.y);
    vec3 r = refract(I, surf_normal(xz, u_time), 1.0 / 1.333);
    return (s + r * ((u_floor - s.y) / r.y)).xz;
}

void main() {
    vec3 I = -normalize(u_sunDir);
    const float e = 0.05;
    vec2 p = land(in_xz, I);
    vec2 jx = (land(in_xz + vec2(e, 0.0), I) - p) / e;
    vec2 jz = (land(in_xz + vec2(0.0, e), I) - p) / e;
    // Energy per floor area = 1 / |Jacobian| of the surface -> floor mapping;
    // a flat surface gives exactly 1. It is evaluated per vertex (no screen
    // derivatives) so the caustic map stays smooth.
    float det = abs(jx.x * jz.y - jx.y * jz.x);
    v_flux = min(1.0 / max(det, 0.05), 10.0);
    vec2 uv = (p - u_mapOrigin) / u_mapSize;
    gl_Position = vec4(uv * 2.0 - 1.0, 0.0, 1.0);
}
"""

CAUSTIC_FS = """
#version 330
in float v_flux;
out vec4 o_col;
void main() { o_col = vec4(v_flux, 0.0, 0.0, 1.0); }
"""

# The underside of the water, seen from below, is a mirror (total internal
# reflection). Trace the reflected ray against the sea floor and the ellipsoids.
MIRROR_FS = "#version 330\n" + COMMON + """
uniform mat4 u_invVP;
in vec2 uv;
out vec4 o_col;

void main() {
    vec3 ro = u_camPos;
    vec4 w = u_invVP * vec4(uv * 2.0 - 1.0, 1.0, 1.0);
    vec3 rd = normalize(w.xyz / w.w - ro);
    vec3 bgc = bg_color(uv) + u_sunCol * 0.06 * pow(clamp(uv.y, 0.0, 1.0), 4.0);
    if (rd.y < 0.004) { o_col = vec4(bgc, 1.0); return; }

    float t = (u_surf - ro.y) / rd.y;
    float detail = clamp(1.45 - t * 0.045, 0.0, 1.0);        // fewer small waves with distance
    vec3 hit = ro + rd * t;
    t += (surf_h_lod(hit.xz, u_time, detail) - hit.y) / rd.y;
    hit = ro + rd * t;
    vec3 n = -surf_normal_lod(hit.xz, u_time, detail);
    vec3 R = reflect(rd, n);
    float window = smoothstep(0.58, 0.72, abs(dot(rd, n)));   // Snell's window: sky shows through

    float tf = -1.0;
    if (R.y < -0.001) {
        float tt = (u_floor - hit.y) / R.y;
        for (int i = 0; i < 4; i++) {
            vec3 p = hit + R * tt;
            tt += (floor_h(p.xz) - p.y) / R.y;
        }
        if (tt > 0.0 && tt < 70.0) tf = tt;
    }
    float te = 1e9;
    int hid = -1;
    vec3 hn = vec3(0.0, 1.0, 0.0);
    for (int i = 0; i < u_nocc; i++) {
        vec3 oc = hit - texelFetch(u_occ, ivec2(i, 0), 0).xyz;
        float rmax = texelFetch(u_occ, ivec2(i, 3), 0).w;
        float b = dot(oc, R);
        if ((b > 0.0 && dot(oc, oc) > rmax * rmax) || dot(oc, oc) - b * b > rmax * rmax) continue;
        Occ o = load_occ(i);
        if (o.opac < 0.5) continue;
        vec3 nn;
        float th = ell_hit(o, hit, R, nn);
        if (th > 0.0 && th < te) { te = th; hid = i; hn = nn; }
    }

    vec3 L = normalize(u_sunDir);
    vec3 col = bgc;
    float tt = 70.0;
    if (hid >= 0 && (tf < 0.0 || te < tf)) {
        vec3 hp = hit + R * te;
        col = load_occ(hid).col * (ambient(hn) + u_sunCol * max(dot(hn, L), 0.0) * 0.8 * sun_atten(hp));
        tt = te;
    } else if (tf > 0.0) {
        vec3 hp = hit + R * tf;
        float flux = rt_flux(hp, 2.0 + log2(1.0 + tf * 0.25)) * 0.5;
        col = vec3(0.80, 0.72, 0.52) * (ambient(vec3(0.0, 1.0, 0.0))
            + u_sunCol * sun_atten(hp) * (0.7 + 0.9 * flux));
        tt = tf;
    }
    float total = t + tt;
    col = mix(col * 1.25 * exp(-vec3(0.10, 0.04, 0.015) * total * 0.30), bgc,
              1.0 - exp(-total * u_fog * 0.8));         // the surface is lit from above
    vec3 Rr = refract(rd, n, 1.333);                         // water -> air, bent away from the normal
    vec3 Ls = normalize(u_sunDir);
    float sd = (dot(Rr, Rr) > 1e-6) ? max(dot(normalize(Rr), Ls), 0.0) : 0.0;
    vec3 sky = mix(vec3(0.78, 0.89, 1.0), vec3(0.16, 0.42, 0.92), pow(clamp(Rr.y, 0.0, 1.0), 0.55));
    sky = sky * (0.12 + 0.88 * u_day) + u_sunCol * (pow(sd, 600.0) * 12.0 + pow(sd, 14.0) * 0.5);
    col = mix(col, sky, window * 0.9);
    o_col = vec4(col, 1.0);
}
"""

# Volumetric light: march each camera ray through the water; at every step the
# light that arrives is the caustic flux (sun rays focused by the surface) times
# the shadow rays against the ellipsoids, attenuated with depth.
VOL_FS = "#version 330\n" + COMMON + """
uniform sampler2D u_scene;      // alpha = distance to the nearest surface (0 = none)
uniform mat4 u_invVP;
uniform float u_scale;          // scene pixels per volume pixel
uniform int u_steps;
uniform float u_vol;
in vec2 uv;
out vec4 o_col;
void main() {
    vec3 ro = u_camPos;
    vec4 w = u_invVP * vec4(uv * 2.0 - 1.0, 1.0, 1.0);
    vec3 dir = normalize(w.xyz / w.w - ro);
    float dist = texelFetch(u_scene, ivec2(gl_FragCoord.xy * u_scale), 0).a;
    float maxd = dist > 0.0 ? dist : 48.0;
    if (dir.y > 0.0001) maxd = min(maxd, (u_surf - ro.y) / dir.y);
    maxd = min(maxd, 48.0);

    vec3 L = normalize(u_sunDir);
    float jit = hash12(gl_FragCoord.xy + fract(u_time) * 37.0);
    float dt = maxd / float(u_steps);
    float phase = 0.30 + 0.70 * pow(max(dot(dir, L), 0.0), 3.0);
    vec3 acc = vec3(0.0);
    float T = 1.0;
    for (int i = 0; i < u_steps; i++) {
        vec3 p = ro + dir * ((float(i) + jit) * dt);
        float lit = rt_flux(p, 3.0) * rt_shadow(p, L, -1);
        float atten = exp(-max(u_surf - p.y, 0.0) * 0.11);
        acc += T * lit * atten * dt * 0.05;
        T *= exp(-0.05 * dt);
    }
    o_col = vec4(u_sunCol * acc * phase * u_vol, 1.0);
}
"""

BLIT_FS = """
#version 330
uniform sampler2D u_tex;
in vec2 uv;
out vec4 o_col;
void main() { o_col = vec4(texture(u_tex, uv).rgb, 0.0); }
"""


# Depth of field: gather blur whose radius follows the circle of confusion of
# each pixel (distance is stored in the scene's alpha channel).
DOF_FS = """
#version 330
uniform sampler2D u_scene;
uniform vec2 u_texel;
uniform float u_focus;
uniform float u_strength;     // maximum blur radius in pixels
uniform float u_time;
in vec2 uv;
out vec4 o_col;

float coc(float dist) {
    float d = dist > 0.0 ? dist : 60.0;
    float k = (d < u_focus) ? 1.1 : 0.45;               // nearer objects blur more than far ones
    return clamp(abs(1.0 / u_focus - 1.0 / d) * u_focus * k, 0.0, 1.0) * u_strength;
}
float ign(vec2 p) { return fract(52.9829189 * fract(dot(p, vec2(0.06711056, 0.00583715)))); }

void main() {
    vec4 center = texture(u_scene, uv);
    if (any(isnan(center.rgb)) || any(isinf(center.rgb))) center.rgb = vec3(0.0);
    float cc = coc(center.a);
    if (cc < 0.6) { o_col = center; return; }
    float ang0 = ign(gl_FragCoord.xy + fract(u_time) * 40.0) * 6.2831853;
    vec3 acc = center.rgb;
    float wsum = 1.0;
    for (int i = 0; i < 18; i++) {
        float r = sqrt((float(i) + 0.5) / 18.0);
        float a = ang0 + float(i) * 2.399963;
        vec4 s = texture(u_scene, uv + vec2(cos(a), sin(a)) * r * cc * u_texel);
        // a neighbour contributes if it lies behind us, or if its own blur reaches this far
        float w = (s.a == 0.0 || s.a >= center.a - 0.25) ? 1.0 : smoothstep(0.0, 1.0, coc(s.a) - r * cc + 1.0);
        acc += ((any(isnan(s.rgb)) || any(isinf(s.rgb))) ? center.rgb : s.rgb) * w;
        wsum += w;
    }
    o_col = vec4(acc / wsum, center.a);
}
"""


# Temporal anti-aliasing: reproject last frame's result through the camera
# (distance is in the alpha channel), clamp it to the local colour range of the
# current frame to reject ghosts, and blend. It also averages the noisy
# stochastic effects (AO rays, volume jitter, depth-of-field taps).
TAA_FS = """
#version 330
uniform sampler2D u_cur;
uniform sampler2D u_hist;
uniform sampler2D u_vel;
uniform mat4 u_invVP;
uniform mat4 u_prevVP;
uniform vec3 u_camPos;
uniform float u_first;
in vec2 uv;
out vec4 o_col;
bool bad3(vec3 c) { return any(isnan(c)) || any(isinf(c)); }
void main() {
    ivec2 px = ivec2(gl_FragCoord.xy);
    ivec2 sz = textureSize(u_cur, 0);
    vec4 cur = texelFetch(u_cur, px, 0);
    bool curBad = bad3(cur.rgb);

    vec3 mn = vec3(1e9), mx = vec3(-1e9), m1 = vec3(0.0), m2 = vec3(0.0);
    float n = 0.0;
    for (int j = -1; j <= 1; j++) {
        for (int i = -1; i <= 1; i++) {
            if (i == 0 && j == 0) continue;
            vec3 c = texelFetch(u_cur, clamp(px + ivec2(i, j), ivec2(0), sz - 1), 0).rgb;
            if (bad3(c)) continue;
            mn = min(mn, c); mx = max(mx, c); m1 += c; m2 += c * c; n += 1.0;
        }
    }
    if (n < 1.0) { m1 = vec3(0.0); m2 = vec3(0.0); mn = vec3(0.0); mx = vec3(0.0); n = 1.0; }
    if (curBad) cur.rgb = m1 / n;                     // heal an isolated NaN/Inf from its neighbours
    mn = min(mn, cur.rgb); mx = max(mx, cur.rgb);
    m1 += cur.rgb; m2 += cur.rgb * cur.rgb; n += 1.0;
    vec3 mu = m1 / n;
    vec3 sd = sqrt(max(m2 / n - mu * mu, 0.0));
    vec3 lo = min(mu - 1.5 * sd, cur.rgb);
    vec3 hi = max(mu + 1.5 * sd, cur.rgb);

    vec2 suv = (vec2(px) + 0.5) / vec2(sz);
    vec4 w = u_invVP * vec4(suv * 2.0 - 1.0, 1.0, 1.0);
    vec3 dir = normalize(w.xyz / w.w - u_camPos);
    float dist = cur.a > 0.0 ? cur.a : 120.0;
    vec4 pc = u_prevVP * vec4(u_camPos + dir * dist, 1.0);
    vec2 puv = pc.xy / pc.w * 0.5 + 0.5;
    vec4 vel = texelFetch(u_vel, px, 0);
    if (vel.a > 0.5) { puv = vel.xy; pc.w = 1.0; }          // moving object: its own motion
    bool valid = u_first < 0.5 && pc.w > 0.0 && all(greaterThan(puv, vec2(0.0))) && all(lessThan(puv, vec2(1.0)));
    vec3 hist = texture(u_hist, valid ? puv : vec2(0.5)).rgb;
    if (bad3(hist)) valid = false;                    // never carry a bad history forward
    hist = clamp(hist, lo, hi);
    o_col = vec4(valid ? mix(cur.rgb, hist, 0.88) : cur.rgb, cur.a);
}
"""
