trait Tr {
    const CONSTANT: usize;

    fn f(&self) -> usize;
}

struct S;

impl Tr for S {
    const CONSTANT: usize = 42;

    fn f(&self) -> usize { Self::CONSTANT }
}

fn main() {
    let s = S;
    println!("{}", s.f());
}