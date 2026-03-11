trait Twice {
    fn twice(self) -> Self;
}

impl Twice for i64 {
    fn twice(self) -> Self {
        self * 2
    }
}

fn fold_twice() -> i64 {
    let mut acc = 0;
    for i in -500..500i64 {
        acc += i.twice();
    }
    acc
}

fn main() {
    std::hint::black_box(fold_twice());
}
