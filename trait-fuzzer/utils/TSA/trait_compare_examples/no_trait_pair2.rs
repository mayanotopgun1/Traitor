fn id_u32(x: u32) -> u32 {
    x
}

fn sum_ids() -> u32 {
    let mut s = 0;
    for i in 0..1000u32 {
        s += id_u32(i);
    }
    s
}

fn main() {
    std::hint::black_box(sum_ids());
}
