trait Foo<'a>:  {
    type Out;
}
trait Bar {
    fn foo(&self) -> &  Foo<'a, Out = impl Sized + 'a>;
}
fn main() {
    let x: & Bar = &();
     _ = x.foo();
}
