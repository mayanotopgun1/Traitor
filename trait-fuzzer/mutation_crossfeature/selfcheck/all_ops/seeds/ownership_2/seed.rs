trait Do {
    fn run(&self) -> i32;
}

struct S;

impl Do for S {
    fn run(&self) -> i32 { 1 }
}

fn call<T: Do>(t: T) -> i32 {
    t.run()
}

fn main() {
    let s = S;
    println!("{}", call(s));
}
