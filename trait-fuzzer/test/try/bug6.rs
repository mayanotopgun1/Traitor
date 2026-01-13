trait Baz{}
impl Baz for () {}
impl<T> Baz for (T,) {}

trait Grault {
    type A;
    type B;
}
impl<T: Grault> Grault for (T,)
where
    Self::A: Baz,
    Self::B: Baz,
{
    type A = ();
    type B = ();
}



fn main() {
    let x: <(_,) as Grault>::A = ();
}