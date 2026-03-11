trait Tr {
    fn f(&self) -> usize;
}

struct S;

impl Tr for S {
    fn f(&self) -> usize { 1 }
}

fn main() {
    let s = S;
    println!("{}", s.f());
}
