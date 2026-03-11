trait Do {
    fn run(self) -> i32;
}

struct S(i32);

impl Do for S {
    fn run(self) -> i32 { self.0 }
}

fn run_all<T: Do>(t: T) -> i32 {
    t.run()
}

fn main() {
    let s = S(2);
    println!("{}", run_all(s));
}