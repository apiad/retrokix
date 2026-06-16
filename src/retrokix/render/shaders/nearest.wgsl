@group(0) @binding(0) var src: texture_2d<f32>;
@group(0) @binding(1) var src_sampler: sampler;

struct Uniforms {
    output_res: vec2<f32>,
    source_res: vec2<f32>,
    frame: f32,
    _pad: f32,
};
@group(0) @binding(2) var<uniform> u: Uniforms;

@fragment
fn fs_main(@builtin(position) frag_pos: vec4<f32>) -> @location(0) vec4<f32> {
    let uv = frag_pos.xy / u.output_res;
    return textureSample(src, src_sampler, uv);
}
