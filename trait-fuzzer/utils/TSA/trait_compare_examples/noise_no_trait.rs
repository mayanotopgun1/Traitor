fn core(x: i32) -> i32 { x + 1 }
fn main() {
    let mut s = 0;
    for i in 0..1000 { s += core(i); }
    std::hint::black_box(s);
}
