// Single-pass CRT shader inspired by Timothy Lottes' work.
// Scanlines + horizontal phosphor mask, gamma-aware blending.

@group(0) @binding(0) var src: texture_2d<f32>;
@group(0) @binding(1) var src_sampler: sampler;

struct Uniforms {
    output_res: vec2<f32>,
    source_res: vec2<f32>,
    frame: f32,
    _pad: f32,
};
@group(0) @binding(2) var<uniform> u: Uniforms;

const HARD_SCAN: f32 = -8.0;     // scanline darkness (more negative = darker)
const HARD_PIX: f32  = -3.0;     // pixel sharpness in the horizontal direction
const MASK_DARK: f32 = 0.5;
const MASK_LIGHT: f32 = 1.5;
const GAMMA: f32 = 2.4;

fn to_linear(c: vec3<f32>) -> vec3<f32> {
    return pow(c, vec3<f32>(GAMMA));
}

fn to_srgb(c: vec3<f32>) -> vec3<f32> {
    return pow(max(c, vec3<f32>(0.0)), vec3<f32>(1.0 / GAMMA));
}

fn fetch(px: vec2<f32>) -> vec3<f32> {
    let clamped = clamp(px, vec2<f32>(0.0), u.source_res - vec2<f32>(1.0));
    let uv = (clamped + vec2<f32>(0.5)) / u.source_res;
    return to_linear(textureSample(src, src_sampler, uv).rgb);
}

fn dist(pos: vec2<f32>) -> vec2<f32> {
    let p = pos * u.source_res;
    return -((p - floor(p)) - vec2<f32>(0.5));
}

fn gauss(pos: f32, scale: f32) -> f32 {
    return exp2(scale * pos * pos);
}

// 3-tap horizontal sample at integer row `row_offset` above/below the source row.
fn horz3(uv: vec2<f32>, row_offset: f32) -> vec3<f32> {
    let src_x = floor(uv.x * u.source_res.x);
    let src_y = floor(uv.y * u.source_res.y) + row_offset;
    let b = fetch(vec2<f32>(src_x - 1.0, src_y));
    let c = fetch(vec2<f32>(src_x + 0.0, src_y));
    let d = fetch(vec2<f32>(src_x + 1.0, src_y));
    let dst = dist(uv);
    let wb = gauss(dst.x - 1.0, HARD_PIX);
    let wc = gauss(dst.x + 0.0, HARD_PIX);
    let wd = gauss(dst.x + 1.0, HARD_PIX);
    return (b * wb + c * wc + d * wd) / (wb + wc + wd);
}

fn scan(uv: vec2<f32>, off: f32) -> f32 {
    let dst = dist(uv);
    return gauss(dst.y + off, HARD_SCAN);
}

fn mask_rgb(screen_xy: vec2<f32>) -> vec3<f32> {
    // Simple 3-stripe horizontal phosphor mask.
    let p = screen_xy.x + screen_xy.y * 2.0;
    let m = floor(p) - 3.0 * floor(p / 3.0);
    var mask = vec3<f32>(MASK_DARK);
    if (m < 1.0) {
        mask.r = MASK_LIGHT;
    } else if (m < 2.0) {
        mask.g = MASK_LIGHT;
    } else {
        mask.b = MASK_LIGHT;
    }
    return mask;
}

@fragment
fn fs_main(@builtin(position) frag_pos: vec4<f32>) -> @location(0) vec4<f32> {
    let uv = frag_pos.xy / u.output_res;
    let a = horz3(uv, -1.0) * scan(uv, -1.0);
    let b = horz3(uv,  0.0) * scan(uv,  0.0);
    let c = horz3(uv,  1.0) * scan(uv,  1.0);
    var rgb = a + b + c;
    rgb = rgb * mask_rgb(frag_pos.xy);
    return vec4<f32>(to_srgb(rgb), 1.0);
}
