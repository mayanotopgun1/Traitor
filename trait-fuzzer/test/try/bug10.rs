trait Tr1{
    type Assoc;
};
trait Tr2{};
struct A;
struct B;
struct C;
impl Tr1 for A{
    type Assoc = B;
}
impl Tr2 for B{}
impl Tr2 for C{}
fn main(){}