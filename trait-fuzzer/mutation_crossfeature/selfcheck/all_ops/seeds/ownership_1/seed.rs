struct S;

impl S {
    fn id(&self) -> i32 { 1 }
}

fn main() {
    let s = S;
    println!("{}", s.id());
}
