trait Tr<'a> {
    fn view(&'a self) -> i32;
}

struct S(i32);

impl<'a> Tr<'a> for S {
    fn view(&'a self) -> i32 { self.0 }
}

struct Wrapper<T>(T);

impl<T> Wrapper<T>
where
    T: Clone,
{
    fn consume(&self) -> i32 { 0 }
}

fn main() {
    let w = Wrapper(S(1));
    println!("{}", w.consume());
}
