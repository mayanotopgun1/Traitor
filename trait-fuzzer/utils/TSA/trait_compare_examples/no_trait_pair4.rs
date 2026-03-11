fn to_len(s: &str) -> usize {
    s.len()
}

fn total_len() -> usize {
    let arr = ["aa", "bbb", "cccc", "d"];
    arr.iter().map(|x| to_len(x)).sum()
}

fn main() {
    std::hint::black_box(total_len());
}
