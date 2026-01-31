fn simple(x: i32, y: f64) {}

struct Foo;
impl Foo {
    fn method(&self, z: i32) {}
    fn method_mut(&mut self) {}
    fn method_typed(self, k: Foo) {}
}

fn with_generics<T>(t: T) {}
