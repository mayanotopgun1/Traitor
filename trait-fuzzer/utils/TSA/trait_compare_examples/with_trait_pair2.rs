trait Id {
    fn id(self) -> Self;
}

impl Id for u32 {
    fn id(self) -> Self {
        self
    }
}

fn sum_ids() -> u32 {
    let mut s = 0;
    for i in 0..1000u32 {
        s += i.id();
    }
    s
}

fn main() {
    std::hint::black_box(sum_ids());
}
