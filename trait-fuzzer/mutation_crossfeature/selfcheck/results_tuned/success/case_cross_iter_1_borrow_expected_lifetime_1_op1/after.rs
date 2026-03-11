struct S {
    v: i32,
}

fn take_by_value(s: &S) -> i32 {
    s.v
}

fn pass_through(s: S) -> i32 {
    take_by_value(&s)
}

fn main() {
    let s = S { v: 7 };
    let out = pass_through(s);
    println!("{}", out);
}