trait Work {
    fn work(&self) -> i32;
}

#[derive(Debug)]
struct S(i32);

impl Work for S {
    fn work(&self) -> i32 { self.0 }
}

fn process<T>(t: T)
where
    T: Work,
{
    let _ = t.work();
}

fn main() {
    process(S(1));
}
