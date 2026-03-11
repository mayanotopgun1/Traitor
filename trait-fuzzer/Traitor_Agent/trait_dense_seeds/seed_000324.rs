#![allow(dead_code)]
#![feature(type_alias_impl_trait)]

#![deny(non_snake_case)]

trait Greeter { fn greet(&self); }
struct Unit;
impl Greeter for Unit {
    fn greet(&self) {
        crate::你好();
    }
}

type GreeterAlias = impl Greeter;

#[define_opaque(GreeterAlias)]
fn make_greeter() -> GreeterAlias {
    Unit
}

fn 你好() {}

fn main() {
    let greeter: GreeterAlias = make_greeter();
    greeter.greet();
}