trait tr1{
    type Assoc;
}
trait tr2{}
struct C;
impl tr2 for C{}
struct A;
struct B;
trait c {}
impl tr1 for A{
    type Assoc = B;
}
fn f<T: tr1>(){
    let _ : <T as tr1>::Assoc;
}

fn main(){}