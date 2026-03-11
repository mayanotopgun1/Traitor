use std::fmt::Debug;

struct S(i32);

fn process<T>(t: T)
where
    T: Debug,
{
    let _ = format!("{:?}", t);
}

fn main() {
    process(S(1));
}
