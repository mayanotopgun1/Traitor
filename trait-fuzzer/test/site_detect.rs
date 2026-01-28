use std::fmt::Debug;


trait Source {
    type Item;
}

trait Transform {
    type Output;
}

trait Consume {
    fn consume(&self);
}


struct A;
struct B;
struct C;

impl Source for A {
    type Item = i32;
}

// B 产生 String
impl Source for B {
    type Item = String;
}

// C 可以把 i32 变成 bool
impl Transform for C {
    type Output = bool;
}

impl<T> Consume for T
where
    T: Source,
    T::Item: Debug,
{
    fn consume(&self) {
        println!("consuming something debuggable");
    }
}


impl<T> Consume for T
where
    T: Source,
    T::Item: Transform,
    <T::Item as Transform>::Output: Debug,
{
    fn consume(&self) {
        println!("consuming something transformable");
    }
}


impl Transform for i32 {
    type Output = bool;
}


fn main() {
    let a = A;
    let b = B;

    a.consume();


    b.consume();
}
