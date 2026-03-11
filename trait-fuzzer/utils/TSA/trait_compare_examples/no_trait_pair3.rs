fn twice(x: i64) -> i64 {
    x * 2
}

fn fold_twice() -> i64 {
    let mut acc = 0;
    for i in -500..500 {
        acc += twice(i);
    }
    acc
}

fn main() {
    std::hint::black_box(fold_twice());
}
