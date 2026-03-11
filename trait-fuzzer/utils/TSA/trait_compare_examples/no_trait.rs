fn add_one(x: i32) -> i32 {
    x + 1
}

fn main() {
    let mut acc = 0;
    for i in 0..1000 {
        acc += add_one(i);
    }
    std::hint::black_box(acc);
}
