struct S {
    v: i32,
}

impl Drop for S {
    fn drop(&mut self) {}
}

impl S {
    fn new(v: i32) -> Self { Self { v } }
}

fn main() {
    let s = S::new(10);
    println!("{}", s.v);
}