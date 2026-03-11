fn core(x: i32) -> i32 { x + 1 }

trait DeadTrait<T> {
    type Out;
    fn dead_call(_: T) -> Self::Out;
}

impl DeadTrait<i32> for i32 {
    type Out = i32;
    fn dead_call(_: i32) -> Self::Out { 0 }
}

fn main() {
    let mut s = 0;
    for i in 0..1000 { s += core(i); }
    std::hint::black_box(s);
}
