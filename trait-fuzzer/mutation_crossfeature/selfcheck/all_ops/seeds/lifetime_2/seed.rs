trait Tr<'a> {
    fn view(&'a self) -> i32;
}

#[derive(Clone)]
struct S(i32);

impl<'a> Tr<'a> for S {
    fn view(&'a self) -> i32 { self.0 }
}

fn use_generic<T>(t: &T) -> i32
where
    T: Clone,
{
    let _ = t.clone();
    0
}

fn main() {
    let s = S(3);
    println!("{}", use_generic(&s));
}
