trait Measure {
    fn measure(&self) -> usize;
}

impl Measure for str {
    fn measure(&self) -> usize {
        self.len()
    }
}

fn total_len() -> usize {
    let arr = ["aa", "bbb", "cccc", "d"];
    arr.iter().map(|x| x.measure()).sum()
}

fn main() {
    std::hint::black_box(total_len());
}
