trait AddOne {
    fn add_one(self) -> i32;
}

impl AddOne for i32 {
    fn add_one(self) -> i32 {
        self + 1
    }
}

fn main() {
    let mut acc = 0;
    for i in 0..1000 {
        acc += i.add_one();
    }
    std::hint::black_box(acc);
}
