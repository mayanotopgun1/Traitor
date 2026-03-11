fn core(x: i32) -> i32 { x + 1 }

trait DeadTrait<T> {
    type Out;
    fn dead_call(_: T) -> Self::Out;
}

impl DeadTrait<i32> for i32 {
    type Out = i32;
    fn dead_call(_: i32) -> Self::Out { 0 }
}

struct NeverUsed;
impl NeverUsed {
    fn never() {
        // intentionally unreachable dead path
        if false {
            let _x = <i32 as DeadTrait<i32>>::dead_call(1);
            std::hint::black_box(_x);
        }
    }
}

fn main() {
    let mut s = 0;
    for i in 0..1000 { s += core(i); }
    std::hint::black_box(s);
}
