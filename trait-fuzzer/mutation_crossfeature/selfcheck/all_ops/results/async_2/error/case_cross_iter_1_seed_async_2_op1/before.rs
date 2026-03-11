struct S {
    v: i32,
}

fn work(s: S) -> i32 {
    let x = s.v + 1;
    x
}

fn main() {
    let s = S { v: 1 };
    println!("{}", work(s));
}
