#![allow(dead_code)]

#![deny(non_snake_case)]

trait Greeter { fn greet(); }
impl Greeter for () { fn greet() { crate::你好(); } }

fn 你好() {}

fn main() { <() as Greeter>::greet(); }