#![feature(specialization)]
trait Assoc {
    type Output;
}
default impl<T> Assoc for T {
    type Output = bool;
}
impl Assoc for u8
where
    unDef: Assoc,
{}
trait Foo {}
impl Foo for <u8 as Assoc>::Output {}
fn main() {}
