#![feature(impl_trait_in_assoc_type)]
trait Trait {
    type Assoc2;
}
struct Bar;
impl Trait for Bar
where
    <Bar as Trait>::Assoc2: Trait,
{
    type Assoc2 = impl std::fmt::Debug;
}
struct Foo {
    field: <Bar as Trait>::Assoc2,
}
static BAR: u8 = 42;
static FOO2: &Foo = unsafe { std::mem::transmute(&BAR) };
fn main() {}
